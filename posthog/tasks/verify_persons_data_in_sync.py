import json
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from django.db.models.query import Prefetch
from django.utils.timezone import now

import structlog
from celery import shared_task

from posthog.clickhouse.client import sync_execute
from posthog.models.person import Person

logger = structlog.get_logger(__name__)

# We check up to LIMIT persons between PERIOD_START..PERIOD_END, in batches of BATCH_SIZE
# This helps keep the metric "moving" as we ship fixes or bugs.
LIMIT = 100000
BATCH_SIZE = 500
PERIOD_START = timedelta(hours=1)
PERIOD_END = timedelta(days=2)

GET_PERSON_CH_QUERY = """
SELECT id, version, properties FROM person JOIN (
    SELECT id, max(version) as version, max(is_deleted) as is_deleted, team_id
    FROM person
    WHERE team_id IN %(team_ids)s AND id IN (%(person_ids)s)
    GROUP BY team_id, id
) as person_max ON person.id = person_max.id AND person.version = person_max.version AND person.team_id = person_max.team_id
WHERE team_id IN %(team_ids)s
  AND person_max.is_deleted = 0
  AND id IN (%(person_ids)s)
"""

GET_DISTINCT_IDS_CH_QUERY = """
SELECT distinct_id, argMax(person_id, version) as person_id
FROM person_distinct_id2
WHERE team_id IN %(team_ids)s
GROUP BY team_id, distinct_id
HAVING argMax(is_deleted, version) = 0 AND person_id IN (%(person_ids)s)
"""


@shared_task(max_retries=1, ignore_result=True)
def verify_persons_data_in_sync(
    period_start: timedelta = PERIOD_START,
    period_end: timedelta = PERIOD_END,
    limit: int = LIMIT,
    emit_results: bool = True,
) -> Counter:
    # :KLUDGE: Rather than filter on created_at directly which is unindexed, we look up the latest value in 'id' column
    #   and leverage that to narrow down filtering in an index-efficient way
    max_pk = Person.objects.filter(created_at__lte=now() - period_start).latest("id").id
    person_data = list(
        Person.objects.filter(
            pk__lte=max_pk,
            pk__gte=max_pk - LIMIT * 5,
            created_at__gte=now() - period_end,
        ).values_list("id", "uuid", "team_id")[:limit]
    )
    person_data.sort(key=lambda row: row[2])  # keep persons from same team together

    results = Counter(
        {
            "total": 0,
            "missing_in_clickhouse": 0,
            "version_mismatch": 0,
            "properties_mismatch": 0,
            "distinct_ids_mismatch": 0,
            "properties_mismatch_same_version": 0,
        }
    )
    for i in range(0, len(person_data), BATCH_SIZE):
        batch = person_data[i : i + BATCH_SIZE]
        results += _team_integrity_statistics(batch)

    if emit_results:
        _emit_metrics(results)

    return results


def _team_integrity_statistics(person_data: list[Any]) -> Counter:
    person_ids = [id for id, _, _ in person_data]
    person_uuids = [uuid for _, uuid, _ in person_data]
    team_ids = list({team_id for _, _, team_id in person_data})

    # :TRICKY: To speed up processing, we fetch all models in batch at once and store results in dictionary indexed by person uuid
    pg_persons = _index_by(
        list(
            Person.objects.filter(id__in=person_ids).prefetch_related(
                Prefetch("persondistinctid_set", to_attr="distinct_ids_cache")
            )
        ),
        lambda p: p.uuid,
    )

    ch_persons = _index_by(
        sync_execute(GET_PERSON_CH_QUERY, {"person_ids": person_uuids, "team_ids": team_ids}),
        lambda row: row[0],
    )

    ch_distinct_ids_mapping = _index_by(
        sync_execute(
            GET_DISTINCT_IDS_CH_QUERY,
            {"person_ids": person_uuids, "team_ids": team_ids},
        ),
        lambda row: row[1],
        flat=False,
    )

    result: Counter = Counter()
    for _pk, uuid, team_id in person_data:
        # Person was deleted in the middle of processing, can ignore
        if uuid not in pg_persons:
            continue
        result["total"] += 1
        pg_person = pg_persons[uuid]
        if uuid not in ch_persons:
            result["missing_in_clickhouse"] += 1
            logger.info("Found person missing in clickhouse", team_id=team_id, uuid=uuid)
            continue
        _, ch_version, ch_properties = ch_persons[uuid]
        ch_properties = json.loads(ch_properties)
        if ch_version != pg_person.version:
            result["version_mismatch"] += 1
            logger.info(
                "Found version mismatch",
                team_id=team_id,
                uuid=uuid,
                properties=pg_person.properties,
                ch_properties=ch_properties,
            )
        if pg_person.properties != ch_properties:
            result["properties_mismatch"] += 1
            logger.info(
                "Found properties mismatch",
                team_id=team_id,
                uuid=uuid,
                properties=pg_person.properties,
                ch_properties=ch_properties,
            )

        # :KLUDGE: Verify business logic. If versions are in sync so should properties be.
        if ch_version != 0 and ch_version == pg_person.version and pg_person.properties != ch_properties:
            result["properties_mismatch_same_version"] += 1

        pg_distinct_ids = sorted(map(str, pg_person.distinct_ids))
        ch_distinct_id = sorted(str(distinct_id) for distinct_id, _ in ch_distinct_ids_mapping.get(uuid, []))
        if pg_distinct_ids != ch_distinct_id:
            result["distinct_ids_mismatch"] += 1
    return result


def _emit_metrics(integrity_results: Counter) -> None:
    from statshog.defaults.django import statsd

    for key, value in integrity_results.items():
        statsd.gauge(f"posthog_person_integrity_{key}", value)


def _index_by(collection: list[Any], key_fn: Any, flat: bool = True) -> dict:
    result: dict = {} if flat else defaultdict(list)
    for item in collection:
        if flat:
            result[key_fn(item)] = item
        else:
            result[key_fn(item)].append(item)
    return result
