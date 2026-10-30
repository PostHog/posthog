"""Group the measures people and agents compute, and find the ones the catalog does not cover.

Human SQL comes from the team's query log. Agent SQL comes from the MCP telemetry, which marks scout
traffic; the query log cannot. Both fold onto one measure fingerprint, so a measure a person and an
agent both compute is one group with one audience.
"""

import json
import asyncio
import hashlib
import dataclasses
from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import UUID

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_async_anthropic_client
from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ..facade.contracts import UncoveredGroup
from ..facade.enums import ShapeOutcome
from .measure_fingerprint import MeasureExtractionError, MeasureFingerprint, extract_measures
from .metric_fingerprint import CatalogIndex
from .usage_adjusted import AgentQuery, fetch_agent_queries
from .usage_judge import JUDGE_MODEL
from .usage_snapshots import usage_snapshot_window, write_payload_sections

logger = structlog.get_logger(__name__)

MAX_GROUPS = 5000
# Scout-only groups rank after every group a person computed. Without a share of the cap, none of them
# fits on a team where people compute more than MAX_GROUPS measures.
SCOUT_GROUPS = 500
MAX_DRAFTS = 200

# Two people computing the same measure is the signal; one person's repeated query is not.
_MIN_PEOPLE = 2
_DRAFT_CONCURRENCY = 8
_MAX_PROMPT_SQL_CHARS = 8000
# The judge model thinks before it answers, and the thinking counts against max_tokens. A draft
# carries a whole HogQL definition, so a smaller budget cuts the JSON off before it closes.
_DRAFT_MAX_TOKENS = 4096

# Only the places where a person writes or saves a query count: insights and dashboard tiles, the SQL
# editor, notebooks, canvases, warehouse views, and the widgets on the Today feed. A built-in product
# page computes the product's own measures, so its queries say nothing about a measure the catalog
# lacks. An allowlist keeps each new product page out. The empty tag is in the list because a web
# app caller that sets no product key is mostly hand-written SQL.
_AUTHORING_PRODUCTS = (
    Product.PRODUCT_ANALYTICS.value,
    Product.SQL_EDITOR.value,
    Product.NOTEBOOKS.value,
    Product.CANVAS.value,
    Product.WAREHOUSE.value,
    Product.TODAY.value,
    "",
)
# Background reads, and the built-in scenes that product analytics tags as its own.
_EXCLUDED_FEATURES = (
    "cache_warmup",
    "alerting",
    "schema_introspection",
    "health_check",
    "data_freshness",
    Feature.EVENT_DEFINITION_SCENE.value,
    Feature.PROPERTY_DEFINITION_SCENE.value,
    Feature.EXPLORE_EVENTS_SCENE.value,
)

# An empty access method marks a request from the web app. Agent traffic is read from the MCP
# telemetry instead, so it is not counted twice.
_HUMAN_SHAPES_SQL = """
SELECT
    anyLast(lc_query__query) AS sample_hogql,
    groupUniqArray(200)(lc_user_id) AS user_ids,
    groupUniqArray(toDate(event_time)) AS active_days,
    count() AS runs
FROM query_log_archive
WHERE team_id = %(team_id)s
  AND event_time >= %(window_start)s
  AND event_time < %(window_end)s
  AND type = 'QueryFinish'
  AND lc_query__query != ''
  AND lc_user_id != 0
  AND lc_access_method = ''
  AND lc_product IN %(authoring_products)s
  AND lc_feature NOT IN %(excluded_features)s
  AND NOT lc_is_impersonated
GROUP BY normalized_query_hash
LIMIT 50000
"""

_DRAFT_SYSTEM_PROMPT = """You help a team curate a catalog of reusable business metrics.

You get a measure that people computed in SQL several times, with one example query.
Decide whether it is a reusable metric worth proposing ("keep": true) or noise ("keep": false):
a probe, a debugging query, a list of rows, or a number about one person or one record.

When you keep it, propose:
- "name": a short snake_case identifier
- "description": one plain sentence that says what the metric counts
- "definition": a HogQL query that computes it over the last 30 days
- "merge_key": a lowercase phrase for the measure, so two spellings of one measure share it

Reply with one JSON object and nothing else:
{"keep": true | false, "name": "...", "description": "...", "definition": "...", "merge_key": "..."}"""


@frozen(frozen=False)
class _Accumulator:
    fingerprint: MeasureFingerprint
    sample_sql: str
    people: set[str]
    days: set[str]
    runs: int = 0
    scout_runs: int = 0


@frozen
class HumanShape:
    sample_sql: str
    user_ids: frozenset[int]
    active_days: frozenset[str]
    runs: int


@frozen
class ProposalDraft:
    name: str
    description: str
    definition: str
    merge_key: str


class _DraftReply(BaseModel):
    keep: bool
    name: str = ""
    description: str = ""
    definition: str = ""
    merge_key: str = ""


class MeasureFolder:
    """Fold human shapes and agent queries onto measure fingerprints."""

    def __init__(self) -> None:
        self._groups: dict[str, _Accumulator] = {}
        self._measures_by_sql: dict[str, list[MeasureFingerprint]] = {}

    def add_human(self, shape: HumanShape, distinct_ids: dict[int, str]) -> None:
        people = {distinct_ids[user_id] for user_id in shape.user_ids if user_id in distinct_ids}
        for measure in self._measures(shape.sample_sql):
            group = self._group(measure, shape.sample_sql)
            group.people.update(people)
            group.days.update(shape.active_days)
            group.runs += shape.runs

    def add_agent(self, query: AgentQuery) -> None:
        for measure in self._measures(query.sql):
            group = self._group(measure, query.sql)
            if query.is_scout:
                group.scout_runs += 1
                continue
            group.people.add(query.distinct_id)
            group.days.add(query.occurred_at.date().isoformat())
            group.runs += 1

    def groups(
        self, index: CatalogIndex, max_groups: int = MAX_GROUPS, scout_groups: int = SCOUT_GROUPS
    ) -> list[UncoveredGroup]:
        """Classified groups, ranked by people, then days, then runs. Scout-only groups come last, ranked by
        scout runs, and keep up to ``scout_groups`` of the ``max_groups`` places."""
        people = [group for group in self._groups.values() if len(group.people) >= _MIN_PEOPLE]
        people.sort(
            key=lambda group: (
                -len(group.people),
                -len(group.days),
                -group.runs,
                -group.scout_runs,
                group.fingerprint.digest,
            )
        )
        scouts = [group for group in self._groups.values() if not group.people and group.scout_runs]
        scouts.sort(key=lambda group: (-group.scout_runs, group.fingerprint.digest))
        scouts = scouts[: min(scout_groups, max_groups)]
        kept = people[: max_groups - len(scouts)] + scouts
        return [_classified(group, index) for group in kept]

    def _measures(self, sql: str) -> list[MeasureFingerprint]:
        key = hashlib.sha256(sql.strip().encode()).hexdigest()
        if key not in self._measures_by_sql:
            try:
                self._measures_by_sql[key] = extract_measures(sql)
            except MeasureExtractionError:
                self._measures_by_sql[key] = []
        return self._measures_by_sql[key]

    def _group(self, measure: MeasureFingerprint, sql: str) -> _Accumulator:
        if measure.digest not in self._groups:
            self._groups[measure.digest] = _Accumulator(fingerprint=measure, sample_sql=sql, people=set(), days=set())
        return self._groups[measure.digest]


def _classified(group: _Accumulator, index: CatalogIndex) -> UncoveredGroup:
    match = index.classify(group.fingerprint)
    return UncoveredGroup(
        fingerprint_digest=group.fingerprint.digest,
        measure=group.fingerprint.describe(),
        outcome=match.outcome,
        matched_metric_id=match.metric_id,
        matched_metric_status=match.metric_status,
        distinct_people=len(group.people),
        active_days=len(group.days),
        runs=group.runs,
        scout_runs=group.scout_runs,
        sample_sql=group.sample_sql,
        draft_name=None,
        draft_description=None,
    )


def apply_drafts(groups: list[UncoveredGroup], drafts: dict[str, ProposalDraft | None]) -> list[UncoveredGroup]:
    """Attach drafts by fingerprint, drop the groups the drafter called noise, and give groups that
    share a merge key the first group's draft, so one measure written two ways gets one proposal."""
    by_merge_key: dict[str, ProposalDraft] = {}
    result: list[UncoveredGroup] = []
    for group in groups:
        if group.fingerprint_digest not in drafts:
            result.append(group)
            continue
        draft = drafts[group.fingerprint_digest]
        if draft is None:
            continue
        shared = by_merge_key.setdefault(draft.merge_key or group.fingerprint_digest, draft)
        result.append(
            dataclasses.replace(
                group,
                draft_name=shared.name,
                draft_description=shared.description,
                draft_definition=shared.definition,
            )
        )
    return result


class DraftFailed(Exception):
    """The drafter's call or reply failed, which says nothing about whether the measure is noise."""


async def draft_proposal(client: AsyncAnthropic, group: UncoveredGroup) -> ProposalDraft | None:
    """A draft metric for the group, or None when the drafter calls it noise.

    Raises DraftFailed when the call or the reply fails, so the caller keeps the group without a draft.
    """
    prompt = (
        f"Measure: {group.measure}\n"
        f"Evidence: {group.distinct_people} people ran it on {group.active_days} days, {group.runs} runs.\n"
        f"Example query:\n{group.sample_sql[:_MAX_PROMPT_SQL_CHARS]}"
    )
    try:
        response = await client.messages.create(
            model=JUDGE_MODEL,
            system=_DRAFT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_DRAFT_MAX_TOKENS,
        )
    except Exception as error:
        raise DraftFailed(f"The draft call failed: {error}") from error
    return parse_draft_reply("".join(block.text for block in response.content if block.type == "text"))


def parse_draft_reply(text: str) -> ProposalDraft | None:
    start, end = text.find("{"), text.rfind("}")
    try:
        reply = _DraftReply.model_validate(json.loads(text[start : end + 1]))
    except (ValueError, ValidationError) as error:
        raise DraftFailed(f"The draft reply was unreadable: {error}") from error
    if not reply.keep or not reply.name:
        return None
    return ProposalDraft(
        name=reply.name, description=reply.description, definition=reply.definition, merge_key=reply.merge_key.lower()
    )


def fetch_human_shapes(*, team: Team, window_start: datetime, window_end: datetime) -> list[HumanShape]:
    with tags_context(product=Product.DATA_CATALOG, feature=Feature.ENRICHMENT, team_id=team.id):
        rows = sync_execute(
            _HUMAN_SHAPES_SQL,
            {
                "team_id": team.id,
                "window_start": window_start,
                "window_end": window_end,
                "authoring_products": _AUTHORING_PRODUCTS,
                "excluded_features": _EXCLUDED_FEATURES,
            },
            team_id=team.id,
            workload=Workload.OFFLINE,
        )
    return [
        HumanShape(
            sample_sql=sample_sql,
            user_ids=frozenset(user_ids),
            active_days=frozenset(str(day) for day in active_days),
            runs=runs,
        )
        for sample_sql, user_ids, active_days, runs in rows
    ]


def _fold_window(*, team_id: int, snapshot_id: UUID, telemetry_team_id: int) -> list[UncoveredGroup]:
    team = Team.objects.get(id=team_id)
    telemetry_team = Team.objects.get(id=telemetry_team_id)
    window = usage_snapshot_window(team_id, snapshot_id)

    folder = MeasureFolder()
    shapes = fetch_human_shapes(team=team, window_start=window.start, window_end=window.end)
    user_ids = {user_id for shape in shapes for user_id in shape.user_ids}
    distinct_ids = dict(User.objects.filter(id__in=user_ids).values_list("id", "distinct_id"))
    for shape in shapes:
        folder.add_human(shape, distinct_ids)
    for query in fetch_agent_queries(
        team=team, telemetry_team=telemetry_team, window_start=window.start, window_end=window.end
    ):
        folder.add_agent(query)
    return folder.groups(CatalogIndex.for_team(team))


def _draft_candidates(groups: Iterable[UncoveredGroup]) -> list[UncoveredGroup]:
    return [group for group in groups if group.outcome == ShapeOutcome.UNCOVERED and group.distinct_people][:MAX_DRAFTS]


async def find_uncovered_into_snapshot(
    *, team_id: int, snapshot_id: UUID, telemetry_team_id: int, heartbeat: Callable[[], None]
) -> int:
    """Fold the window's SQL into measure groups, draft proposals for the top uncovered ones, and
    write the snapshot's ``uncovered`` section."""
    groups = await database_sync_to_async(_fold_window, thread_sensitive=False)(
        team_id=team_id, snapshot_id=snapshot_id, telemetry_team_id=telemetry_team_id
    )
    heartbeat()
    candidates = _draft_candidates(groups)
    semaphore = asyncio.Semaphore(_DRAFT_CONCURRENCY)
    drafts: dict[str, ProposalDraft | None] = {}

    async with build_async_anthropic_client(
        product="django",
        ai_product="data_catalog_usage_drafts",
        team_id=team_id,
        trace_id=f"data-catalog-usage-{snapshot_id}",
    ) as client:

        async def draft(group: UncoveredGroup) -> None:
            async with semaphore:
                try:
                    drafts[group.fingerprint_digest] = await draft_proposal(client, group)
                except DraftFailed as error:
                    logger.warning("data_catalog_usage_draft_failed", error=str(error))
            heartbeat()

        await asyncio.gather(*(draft(group) for group in candidates))

    uncovered = apply_drafts(groups, drafts)
    await database_sync_to_async(write_payload_sections, thread_sensitive=False)(
        team_id, snapshot_id, uncovered=uncovered
    )
    return len(uncovered)
