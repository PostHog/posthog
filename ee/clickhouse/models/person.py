import datetime
import json
from contextlib import ExitStack
from typing import Dict, List, Optional, Union
from uuid import UUID

from django.db.models.query import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now
from rest_framework import serializers

from ee.clickhouse.sql.person import (
    BULK_INSERT_PERSON_DISTINCT_ID2,
    DELETE_PERSON_BY_ID,
    DELETE_PERSON_EVENTS_BY_ID,
    INSERT_PERSON_BULK_SQL,
    INSERT_PERSON_DISTINCT_ID,
    INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_SQL,
)
from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID, KAFKA_PERSON_UNIQUE_ID
from posthog.client import sync_execute
from posthog.models.person import Person, PersonDistinctId
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.settings import TEST

if TEST:
    # :KLUDGE: Hooks are kept around for tests. All other code goes through plugin-server or the other methods explicitly

    @receiver(post_save, sender=Person)
    def person_created(sender, instance: Person, created, **kwargs):
        create_person(
            team_id=instance.team.pk,
            properties=instance.properties,
            uuid=str(instance.uuid),
            is_identified=instance.is_identified,
        )

    @receiver(post_save, sender=PersonDistinctId)
    def person_distinct_id_created(sender, instance: PersonDistinctId, created, **kwargs):
        create_person_distinct_id(instance.team.pk, instance.distinct_id, str(instance.person.uuid))

    @receiver(post_delete, sender=Person)
    def person_deleted(sender, instance: Person, **kwargs):
        delete_person(instance.uuid, instance.properties, instance.is_identified, team_id=instance.team_id)

    @receiver(post_delete, sender=PersonDistinctId)
    def person_distinct_id_deleted(sender, instance: PersonDistinctId, **kwargs):
        create_person_distinct_id(instance.team.pk, instance.distinct_id, str(instance.person.uuid), sign=-1)

    try:
        from freezegun import freeze_time
    except:
        pass

    def bulk_create_persons(persons_list: List[Dict]):
        persons = []
        for _person in persons_list:
            with ExitStack() as stack:
                if _person.get("created_at"):
                    stack.enter_context(freeze_time(_person["created_at"]))
                persons.append(Person(**{key: value for key, value in _person.items() if key != "distinct_ids"}))

        inserted = Person.objects.bulk_create(persons)

        person_inserts = []
        distinct_ids = []
        distinct_id_inserts = []
        for index, person in enumerate(inserted):
            for distinct_id in persons_list[index]["distinct_ids"]:
                distinct_ids.append(
                    PersonDistinctId(person_id=person.pk, distinct_id=distinct_id, team_id=person.team_id)
                )
                distinct_id_inserts.append(f"('{distinct_id}', '{person.uuid}', {person.team_id}, 0, 0, now(), 0, 0)")

            created_at = now().strftime("%Y-%m-%d %H:%M:%S.%f")
            timestamp = now().strftime("%Y-%m-%d %H:%M:%S")
            person_inserts.append(
                f"('{person.uuid}', '{created_at}', {person.team_id}, '{json.dumps(person.properties)}', {'1' if person.is_identified else '0'}, '{timestamp}', 0, 0)"
            )

        PersonDistinctId.objects.bulk_create(distinct_ids)
        sync_execute(INSERT_PERSON_BULK_SQL + ", ".join(person_inserts), flush=False)
        sync_execute(BULK_INSERT_PERSON_DISTINCT_ID2 + ", ".join(distinct_id_inserts), flush=False)


def create_person(
    team_id: int,
    uuid: Optional[str] = None,
    properties: Optional[Dict] = {},
    sync: bool = False,
    is_identified: bool = False,
    timestamp: Optional[datetime.datetime] = None,
) -> str:
    if uuid:
        uuid = str(uuid)
    else:
        uuid = str(UUIDT())
    if not timestamp:
        timestamp = now()

    data = {
        "id": str(uuid),
        "team_id": team_id,
        "properties": json.dumps(properties),
        "is_identified": int(is_identified),
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=data, sync=sync)
    return uuid


def create_person_distinct_id(team_id: int, distinct_id: str, person_id: str, version=0, sign=1) -> None:
    data = {"distinct_id": distinct_id, "person_id": person_id, "team_id": team_id, "_sign": sign}
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_PERSON_UNIQUE_ID, sql=INSERT_PERSON_DISTINCT_ID, data=data)
    if sign == 1:
        p.produce(
            topic=KAFKA_PERSON_DISTINCT_ID,
            sql=INSERT_PERSON_DISTINCT_ID2,
            data={"distinct_id": distinct_id, "person_id": person_id, "team_id": team_id, "version": version,},
        )


def get_persons_by_distinct_ids(team_id: int, distinct_ids: List[str]) -> QuerySet:
    return Person.objects.filter(
        team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id__in=distinct_ids
    )


def get_persons_by_uuids(team: Team, uuids: List[str]) -> QuerySet:
    return Person.objects.filter(team_id=team.pk, uuid__in=uuids)


def delete_person(
    person_id: UUID, properties: Dict, is_identified: bool, delete_events: bool = False, team_id: int = False
) -> None:
    timestamp = now()

    data = {
        "id": person_id,
        "team_id": team_id,
        "properties": json.dumps(properties),
        "is_identified": int(is_identified),
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        if delete_events:
            sync_execute(DELETE_PERSON_EVENTS_BY_ID, {"id": person_id, "team_id": team_id})
    except:
        pass  # cannot delete if the table is distributed

    sync_execute(DELETE_PERSON_BY_ID, data)


def count_duplicate_distinct_ids_for_team(team_id: Union[str, int]) -> Dict:
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(weeks=1)).strftime("%Y-%m-%d %H:%M:%S")
    query_result = sync_execute(
        """
        SELECT
            count(if(startdate < toDate(%(cutoff_date)s), 1, NULL)) as prev_ids_with_duplicates,
            minus(sum(if(startdate < toDate(%(cutoff_date)s), count, 0)), prev_ids_with_duplicates) as prev_total_extra_distinct_id_rows,
            count(if(startdate >= toDate(%(cutoff_date)s), 1, NULL)) as new_ids_with_duplicates,
            minus(sum(if(startdate >= toDate(%(cutoff_date)s), count, 0)), prev_ids_with_duplicates) as new_total_extra_distinct_id_rows
        FROM (
            SELECT distinct_id, count(*) as count, toDate(min(timestamp)) as startdate
            FROM (
                SELECT person_id, distinct_id, max(_timestamp) as timestamp
                FROM person_distinct_id
                WHERE team_id = %(team_id)s
                GROUP BY person_id, distinct_id, team_id
                HAVING max(is_deleted) = 0
            )
            GROUP BY distinct_id
            HAVING count > 1
        ) as duplicates
        """,
        {"team_id": str(team_id), "cutoff_date": cutoff_date},
    )

    result = {
        "prev_total_ids_with_duplicates": query_result[0][0],
        "prev_total_extra_distinct_id_rows": query_result[0][1],
        "new_total_ids_with_duplicates": query_result[0][2],
        "new_total_extra_distinct_id_rows": query_result[0][3],
    }
    return result


def count_total_persons_with_multiple_ids(team_id: Union[str, int], min_ids: int = 2):
    query_result = sync_execute(
        """
        SELECT count(*) as total_persons, max(_count) as max_distinct_ids_for_one_person FROM (
            SELECT person_id, count(distinct_id) as _count
            FROM person_distinct_id
            WHERE team_id = %(team_id)s
            GROUP BY person_id, team_id
            HAVING max(is_deleted) = 0
        )
        WHERE _count > %(min_ids)s
        """,
        {"team_id": str(team_id), "min_ids": str(min_ids)},
    )

    result = {
        f"total_persons_with_more_than_{min_ids}_ids": query_result[0][0],
        "max_distinct_ids_for_one_person": query_result[0][1],
    }
    return result


class ClickhousePersonSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()
    properties = serializers.SerializerMethodField()
    is_identified = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    distinct_ids = serializers.SerializerMethodField()

    def get_name(self, person):
        props = json.loads(person[3])
        email = props.get("email", None)
        return email or person[0]

    def get_id(self, person):
        return person[0]

    def get_created_at(self, person):
        return person[1]

    def get_team_id(self, person):
        return person[2]

    def get_properties(self, person):
        return json.loads(person[3])

    def get_is_identified(self, person):
        return person[4]

    # all queries might not retrieve distinct_ids
    def get_distinct_ids(self, person):
        return person[5] if len(person) > 5 else []
