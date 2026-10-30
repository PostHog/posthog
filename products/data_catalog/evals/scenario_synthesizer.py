"""Deterministic scenario pack for the analysis diligence evals.

Each needle plants one truth that a careful analysis finds and a careless one misses: a real
campaign spike, a bot spike, a tracking bug, a flag that blocks a feature, a sales outlier, a
note in Slack that changes what a number means. Prompts, ``expected`` values, the seeder, and
the scorers all import the constants below, so they can never drift apart.

The module is pure: no Django, no I/O, no clock. Dates are day offsets before "now", and the
seeder resolves them when it writes the rows. All randomness comes from seeded generators, so
two calls return equal packs. Every name, email, and message here is invented.
"""

from __future__ import annotations

import random
from typing import Any

from posthog.dataclasses import frozen

PACK_TOKEN = "evalpack"
PACK_EMAIL_DOMAIN = "example.com"
PACK_SEED = 20261029

# WAU_SPIKE: a sponsored video sends new users to the Hedgebox campaign landing page.
WAU_SPIKE_PERSON_COUNT = 120
WAU_SPIKE_DAYS_AGO = (10, 9, 8)
CAMPAIGN_PATH = "/mariustechtips/"
CAMPAIGN_URL = f"https://hedgebox.net{CAMPAIGN_PATH}"
CAMPAIGN_REFERRER = "https://www.youtube.com/@mariustechtips"
CAMPAIGN_REFERRING_DOMAIN = "www.youtube.com"
CAMPAIGN_UTM_SOURCE = "mariustechtips"
CAMPAIGN_ANNOTATION_CONTENT = "Marius Tech Tips sponsorship went live"
CAMPAIGN_ANNOTATION_DAYS_AGO = WAU_SPIKE_DAYS_AGO[0]

# WAU_BOT_SPIKE: a headless crawler that never logs in. It needs many distinct ids, because a WAU
# count dedupes by user and a few busy ids would not move it.
WAU_BOT_DISTINCT_ID_COUNT = 150
WAU_BOT_PAGEVIEWS_PER_ID = 3
WAU_BOT_DAYS_AGO = WAU_SPIKE_DAYS_AGO
WAU_BOT_BROWSER = "HeadlessChrome"
WAU_BOT_DEVICE_TYPE = "Other"
WAU_BOT_PATHS = ("/", "/pricing/", "/signup/")

# UPLOAD_DOUBLE_COUNT: a client release sends every upload twice.
UPLOAD_EVENT = "uploaded_file"
UPLOAD_DUPLICATE_FROM_DAYS_AGO = 6
UPLOAD_DUPLICATE_TO_DAYS_AGO = 3
UPLOAD_DUPLICATE_LIB_VERSION = "2.0.0-beta.1"

# SHARE_DROP_FLAG: a flag rollout blocks sharing for one cohort.
SHARE_EVENT = "shared_file_link"
SHARE_FLAG_KEY = f"sharing-gate-{PACK_TOKEN}"
SHARE_FLAG_BLOCKED_VARIANT = "blocked"
SHARE_FLAG_CONTROL_VARIANT = "control"
SHARE_BLOCKED_PERSON_COUNT = 60
SHARE_CONTROL_PERSON_COUNT = 20
SHARE_BASELINE_FROM_DAYS_AGO = 30
SHARE_BLOCK_FROM_DAYS_AGO = 9
SHARE_BLOCK_TO_DAYS_AGO = 4
SHARE_BLOCKED_SHARES_PER_DAY = 2

# PREVIEW_ADOPTION: a new feature whose first event is recent.
PREVIEW_EVENT = "previewed_file"
PREVIEW_FIRST_SEEN_DAYS_AGO = 20
PREVIEW_START_SHARE = 0.02
PREVIEW_END_SHARE = 0.25

# MCP_TOOL_SHIPPED: agent tool calls, with one tool that shipped mid-window.
MCP_TOOL_CALL_EVENT = "$mcp_tool_call"
MCP_EXPORT_TOOL = f"{PACK_TOKEN}-export"
MCP_SHARE_TOOL = f"{PACK_TOKEN}-share"
MCP_EXPORT_FIRST_SEEN_DAYS_AGO = 45
MCP_WINDOW_DAYS = 90
MCP_SESSIONS_PER_DAY = 4
MCP_AGENT_USER_COUNT = 12
MCP_BASE_TOOLS = ("execute-sql", "insight-get", "dashboard-get", "read-data-schema")
MCP_SHARE_CALLS_WITH_EXPORT = 3
MCP_SHARE_CALLS_WITHOUT_EXPORT = 1

# REVENUE_REP_OUTLIER: a CRM export where one deal and its duplicate decide the ranking.
CRM_DEALS_SCHEMA = f"crm_deals_{PACK_TOKEN}"
CRM_DEALS_TABLE = f"postgres_{CRM_DEALS_SCHEMA}"
CRM_DEALS_COLUMNS = ("deal_id", "rep_name", "rep_email", "account_name", "closed_on", "amount_usd")
CRM_REP_COUNT = 8
CRM_MONTHS = 10
CRM_DEALS_PER_REP_MONTH = 3
CRM_OUTLIER_FACTOR = 9
CRM_TOP_N = 5
_CRM_REP_NAMES = (
    "Avery Lindqvist",
    "Bastian Okafor",
    "Celine Marchetti",
    "Dmitri Halvorsen",
    "Esme Quarshie",
    "Florin Tanaka",
    "Greta Villanueva",
    "Hugo Abernathy",
)
_CRM_REP_BASE_DEAL_USD = (9000, 8500, 8000, 7600, 7200, 6400, 6000, 5500)
CRM_OUTLIER_REP_NAME = _CRM_REP_NAMES[6]

# SLACK_PRETAX_NOTE and SLACK_UNHAPPY_ACCOUNTS: one Slack export with both needles.
SLACK_MESSAGES_SCHEMA = f"slack_messages_{PACK_TOKEN}"
SLACK_MESSAGES_TABLE = f"postgres_{SLACK_MESSAGES_SCHEMA}"
SLACK_MESSAGES_COLUMNS = ("channel", "ts", "user", "text")
SLACK_NOISE_MESSAGE_COUNT = 200
SLACK_PRETAX_CHANNEL = "#finance"
SLACK_PRETAX_TEXT = "reminder: paid_bill.amount_usd is pre-tax, finance reports post-tax (x1.08)"
SLACK_PRETAX_DAYS_AGO = 40
POST_TAX_MULTIPLIER = 1.08
SLACK_UNHAPPY_CHANNEL = "#support"
SLACK_UNHAPPY_WINDOW_DAYS = 182
SLACK_UNHAPPY_THRESHOLD = 3

# ACCOUNT_HEALTH_TABLE: a churn score per account.
ACCOUNT_HEALTH_SCHEMA = f"account_health_{PACK_TOKEN}"
ACCOUNT_HEALTH_TABLE = f"postgres_{ACCOUNT_HEALTH_SCHEMA}"
ACCOUNT_HEALTH_COLUMNS = ("account_name", "churn_health", "as_of")
ACCOUNT_COUNT = 16
CHURN_HEALTH_THRESHOLD = 5

# ORG_GRAIN_METRIC: an approved metric whose grain is the account, not the user.
ORG_GRAIN_METRIC_NAME = "avg_spend_per_account"
ORG_GRAIN_METRIC_DESCRIPTION = (
    "Average paid_bill spend per account over the trailing 30 days, per account, pre-tax. "
    "Groups bills by the account group, not by person."
)
ORG_GRAIN_METRIC_DEFINITION: dict[str, Any] = {
    "kind": "HogQLQuery",
    "query": (
        "SELECT avg(account_spend) AS avg_spend_per_account\n"
        "FROM (\n"
        "    SELECT $group_0 AS account, sum(toFloat(properties.amount_usd)) AS account_spend\n"
        "    FROM events\n"
        "    WHERE event = 'paid_bill' AND timestamp >= now() - INTERVAL 30 DAY AND $group_0 != ''\n"
        "    GROUP BY account\n"
        ")"
    ),
}

_FIRST_NAMES = (
    "Ada",
    "Bram",
    "Cleo",
    "Dario",
    "Elif",
    "Fenna",
    "Gideon",
    "Hana",
    "Ivo",
    "Juno",
    "Kaia",
    "Lars",
    "Mira",
    "Nils",
    "Odile",
    "Pavel",
    "Quinn",
    "Rosa",
    "Silas",
    "Tove",
)
_LAST_NAMES = (
    "Arkwright",
    "Benedetti",
    "Castellan",
    "Drummond",
    "Esposito",
    "Falk",
    "Grimaldi",
    "Hollis",
    "Ivanova",
    "Jansen",
    "Kowalczyk",
    "Lindgren",
)
_ACCOUNT_NAMES = (
    "Northwind Atelier",
    "Bluefin Logistics",
    "Copperleaf Studio",
    "Driftwood Legal",
    "Emberline Clinics",
    "Foxglove Media",
    "Granite Peak Labs",
    "Harborview Dental",
    "Ironbark Analytics",
    "Juniper Schools",
    "Kestrel Architects",
    "Lumen Retail",
    "Marlow Freight",
    "Nimbus Travel",
    "Oakhurst Bakery",
    "Pinecrest Realty",
)
_SLACK_CHANNELS = ("#general", "#sales", "#support", "#product", "#finance")
_SLACK_NOISE_TEMPLATES = (
    "standup moved to {hour}:30 today",
    "can someone review the onboarding doc before {weekday}?",
    "{account} asked about seat pricing for next quarter",
    "deploy finished, release notes are in the wiki",
    "lunch order closes at {hour}:00",
    "{account} renewed for another year",
    "who owns the {weekday} customer webinar?",
    "dashboard for weekly uploads is pinned in the team channel",
    "reminder to log your time off before {weekday}",
    "{account} wants a demo of team folders",
)
_SLACK_UNHAPPY_TEMPLATES = (
    "{account} is unhappy with sync speed again, they opened another ticket",
    "{account} escalated: unhappy about the storage limit change",
    "call with {account} went badly, they are unhappy with support response times",
)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


@frozen
class PlantedPerson:
    distinct_id: str
    email: str | None
    name: str | None


@frozen
class PlantedEvent:
    event: str
    distinct_id: str
    days_ago: int
    minute_of_day: int
    """Minutes after the start of the day, so per-day order stays stable across runs."""
    properties: dict[str, Any]


@frozen
class EventNeedle:
    name: str
    persons: tuple[PlantedPerson, ...]
    events: tuple[PlantedEvent, ...]


@frozen
class DuplicateSpec:
    """Duplicate every existing ``event`` row in the window with a new uuid and the new library version."""

    event: str
    from_days_ago: int
    to_days_ago: int
    lib_version: str


@frozen
class AdoptionSpec:
    """Plant ``event`` for a share of the team's active users that grows linearly from the first day."""

    event: str
    first_seen_days_ago: int
    start_share: float
    end_share: float

    def share_on(self, days_ago: int) -> float:
        span = self.first_seen_days_ago - 1
        progress = (self.first_seen_days_ago - days_ago) / span if span else 1.0
        return self.start_share + (self.end_share - self.start_share) * progress


@frozen
class FlagNeedle:
    key: str
    variants: tuple[str, ...]
    events: EventNeedle


@frozen
class TableNeedle:
    schema_name: str
    table_name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    """Rows with dates as day offsets; the seeder turns each ``days_ago`` cell into a date string."""
    date_column: str | None


@frozen
class DealRow:
    deal_id: str
    rep_name: str
    rep_email: str
    account_name: str
    days_ago: int
    amount_usd: float


@frozen
class SalesOutlier:
    deals: tuple[DealRow, ...]
    outlier_deal_id: str
    outlier_rep: str
    top_reps_with_outlier: tuple[str, ...]
    top_reps_without_outlier: tuple[str, ...]


@frozen
class SlackExport:
    table: TableNeedle
    unhappy_accounts: tuple[str, ...]
    """Accounts with at least ``SLACK_UNHAPPY_THRESHOLD`` unhappy messages inside the window."""


@frozen
class AccountHealth:
    table: TableNeedle
    at_risk_accounts: tuple[str, ...]
    """Accounts whose ``churn_health`` is above ``CHURN_HEALTH_THRESHOLD``."""


def _person(prefix: str, index: int) -> PlantedPerson:
    first = _FIRST_NAMES[index % len(_FIRST_NAMES)]
    last = _LAST_NAMES[(index // len(_FIRST_NAMES)) % len(_LAST_NAMES)]
    distinct_id = f"{PACK_TOKEN}-{prefix}-{index + 1:03d}"
    return PlantedPerson(distinct_id=distinct_id, email=f"{distinct_id}@{PACK_EMAIL_DOMAIN}", name=f"{first} {last}")


def build_wau_spike() -> EventNeedle:
    persons = tuple(_person("campaign", index) for index in range(WAU_SPIKE_PERSON_COUNT))
    landing = {
        "$current_url": CAMPAIGN_URL,
        "$pathname": CAMPAIGN_PATH,
        "$referrer": CAMPAIGN_REFERRER,
        "$referring_domain": CAMPAIGN_REFERRING_DOMAIN,
        "utm_source": CAMPAIGN_UTM_SOURCE,
    }
    files = {"$current_url": "https://hedgebox.net/files/", "$pathname": "/files/"}
    first_day, *later_days = WAU_SPIKE_DAYS_AGO
    events: list[PlantedEvent] = []
    for index, person in enumerate(persons):
        minute = 60 + (index * 7) % 1200
        events += [
            PlantedEvent(
                event="$pageview",
                distinct_id=person.distinct_id,
                days_ago=first_day,
                minute_of_day=minute,
                properties=landing,
            ),
            PlantedEvent(
                event="signed_up",
                distinct_id=person.distinct_id,
                days_ago=first_day,
                minute_of_day=minute + 2,
                properties={"from_invite": False},
            ),
            PlantedEvent(
                event="logged_in",
                distinct_id=person.distinct_id,
                days_ago=first_day,
                minute_of_day=minute + 3,
                properties={},
            ),
        ]
        for day in later_days:
            events += [
                PlantedEvent(
                    event="logged_in", distinct_id=person.distinct_id, days_ago=day, minute_of_day=minute, properties={}
                ),
                PlantedEvent(
                    event="$pageview",
                    distinct_id=person.distinct_id,
                    days_ago=day,
                    minute_of_day=minute + 1,
                    properties=files,
                ),
            ]
    return EventNeedle(name="wau_spike", persons=persons, events=tuple(events))


def build_wau_bot_spike() -> EventNeedle:
    persons = tuple(
        PlantedPerson(distinct_id=f"{PACK_TOKEN}-crawler-{index + 1:03d}", email=None, name=None)
        for index in range(WAU_BOT_DISTINCT_ID_COUNT)
    )
    events: list[PlantedEvent] = []
    for index, person in enumerate(persons):
        day = WAU_BOT_DAYS_AGO[index % len(WAU_BOT_DAYS_AGO)]
        for hit in range(WAU_BOT_PAGEVIEWS_PER_ID):
            path = WAU_BOT_PATHS[hit % len(WAU_BOT_PATHS)]
            events.append(
                PlantedEvent(
                    event="$pageview",
                    distinct_id=person.distinct_id,
                    days_ago=day,
                    minute_of_day=(index * 3 + hit) % 1440,
                    properties={
                        "$current_url": f"https://hedgebox.net{path}",
                        "$pathname": path,
                        "$browser": WAU_BOT_BROWSER,
                        "$device_type": WAU_BOT_DEVICE_TYPE,
                        "$os": "Linux",
                    },
                )
            )
    return EventNeedle(name="wau_bot_spike", persons=persons, events=tuple(events))


UPLOAD_DOUBLE_COUNT = DuplicateSpec(
    event=UPLOAD_EVENT,
    from_days_ago=UPLOAD_DUPLICATE_FROM_DAYS_AGO,
    to_days_ago=UPLOAD_DUPLICATE_TO_DAYS_AGO,
    lib_version=UPLOAD_DUPLICATE_LIB_VERSION,
)

PREVIEW_ADOPTION = AdoptionSpec(
    event=PREVIEW_EVENT,
    first_seen_days_ago=PREVIEW_FIRST_SEEN_DAYS_AGO,
    start_share=PREVIEW_START_SHARE,
    end_share=PREVIEW_END_SHARE,
)

_SHARE_PROPS = {"file_type": "application/pdf", "file_size_b": 2_097_152}


def build_share_drop_flag() -> FlagNeedle:
    blocked = tuple(_person("sharer", index) for index in range(SHARE_BLOCKED_PERSON_COUNT))
    control = tuple(
        _person("sharer", index)
        for index in range(SHARE_BLOCKED_PERSON_COUNT, SHARE_BLOCKED_PERSON_COUNT + SHARE_CONTROL_PERSON_COUNT)
    )
    events: list[PlantedEvent] = []
    for cohort, variant in ((blocked, SHARE_FLAG_BLOCKED_VARIANT), (control, SHARE_FLAG_CONTROL_VARIANT)):
        for index, person in enumerate(cohort):
            minute = 30 + (index * 11) % 1200
            for day in range(SHARE_BASELINE_FROM_DAYS_AGO, 0, -1):
                events.append(
                    PlantedEvent(
                        event="logged_in",
                        distinct_id=person.distinct_id,
                        days_ago=day,
                        minute_of_day=minute,
                        properties={},
                    )
                )
                in_block = SHARE_BLOCK_TO_DAYS_AGO <= day <= SHARE_BLOCK_FROM_DAYS_AGO
                if in_block:
                    events.append(
                        PlantedEvent(
                            event="$feature_flag_called",
                            distinct_id=person.distinct_id,
                            days_ago=day,
                            minute_of_day=minute + 1,
                            properties={
                                "$feature_flag": SHARE_FLAG_KEY,
                                "$feature_flag_response": variant,
                                f"$feature/{SHARE_FLAG_KEY}": variant,
                            },
                        )
                    )
                blocked_now = variant == SHARE_FLAG_BLOCKED_VARIANT and day <= SHARE_BLOCK_FROM_DAYS_AGO
                shares = (
                    0 if blocked_now else (SHARE_BLOCKED_SHARES_PER_DAY if variant == SHARE_FLAG_BLOCKED_VARIANT else 1)
                )
                events += [
                    PlantedEvent(
                        event=SHARE_EVENT,
                        distinct_id=person.distinct_id,
                        days_ago=day,
                        minute_of_day=minute + 2 + share,
                        properties=_SHARE_PROPS,
                    )
                    for share in range(shares)
                ]
    return FlagNeedle(
        key=SHARE_FLAG_KEY,
        variants=(SHARE_FLAG_CONTROL_VARIANT, SHARE_FLAG_BLOCKED_VARIANT),
        events=EventNeedle(name="share_drop_flag", persons=blocked + control, events=tuple(events)),
    )


def build_mcp_tool_shipped() -> EventNeedle:
    rng = random.Random(PACK_SEED + 1)
    persons = tuple(_person("agent", index) for index in range(MCP_AGENT_USER_COUNT))
    events: list[PlantedEvent] = []
    for day in range(MCP_WINDOW_DAYS, 0, -1):
        for session in range(MCP_SESSIONS_PER_DAY):
            person = persons[(day * MCP_SESSIONS_PER_DAY + session) % len(persons)]
            session_id = f"{PACK_TOKEN}-session-{day:03d}-{session}"
            shipped = day <= MCP_EXPORT_FIRST_SEEN_DAYS_AGO
            uses_export = shipped and session % 2 == 0
            tools = list(rng.sample(MCP_BASE_TOOLS, k=2))
            if uses_export:
                tools.append(MCP_EXPORT_TOOL)
            share_calls = MCP_SHARE_CALLS_WITH_EXPORT if uses_export else MCP_SHARE_CALLS_WITHOUT_EXPORT
            tools += [MCP_SHARE_TOOL] * share_calls
            start = 120 + session * 240
            for step, tool in enumerate(tools):
                events.append(
                    PlantedEvent(
                        event=MCP_TOOL_CALL_EVENT,
                        distinct_id=person.distinct_id,
                        days_ago=day,
                        minute_of_day=start + step,
                        properties={
                            "tool_name": tool,
                            "$mcp_tool_name": tool,
                            "$mcp_duration_ms": 200 + rng.randrange(1800),
                            "$mcp_is_error": False,
                            "$session_id": session_id,
                        },
                    )
                )
    return EventNeedle(name="mcp_tool_shipped", persons=persons, events=tuple(events))


def _rep_email(name: str) -> str:
    return f"{name.lower().replace(' ', '.')}.{PACK_TOKEN}@{PACK_EMAIL_DOMAIN}"


def _top_reps(deals: list[DealRow], n: int) -> tuple[str, ...]:
    totals: dict[str, float] = {}
    for deal in deals:
        totals[deal.rep_name] = totals.get(deal.rep_name, 0.0) + deal.amount_usd
    return tuple(name for name, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:n])


def build_revenue_rep_outlier() -> SalesOutlier:
    rng = random.Random(PACK_SEED + 2)
    deals: list[DealRow] = []
    for month in range(CRM_MONTHS):
        for rep_index, rep_name in enumerate(_CRM_REP_NAMES[:CRM_REP_COUNT]):
            for slot in range(CRM_DEALS_PER_REP_MONTH):
                amount = round(_CRM_REP_BASE_DEAL_USD[rep_index] * rng.uniform(0.7, 1.3), 2)
                deals.append(
                    DealRow(
                        deal_id=f"D-{month:02d}{rep_index}{slot}",
                        rep_name=rep_name,
                        rep_email=_rep_email(rep_name),
                        account_name=rng.choice(_ACCOUNT_NAMES),
                        days_ago=1 + month * 30 + rng.randrange(28),
                        amount_usd=amount,
                    )
                )
    without_outlier = _top_reps(deals, CRM_TOP_N)
    largest = max(deal.amount_usd for deal in deals)
    outlier = DealRow(
        deal_id="D-OUTLIER",
        rep_name=CRM_OUTLIER_REP_NAME,
        rep_email=_rep_email(CRM_OUTLIER_REP_NAME),
        account_name=_ACCOUNT_NAMES[0],
        days_ago=1 + 4 * 30 + 12,
        amount_usd=round(largest * CRM_OUTLIER_FACTOR, 2),
    )
    # The duplicate is an identical row, as a second export of the same deal would produce.
    with_outlier = [*deals, outlier, outlier]
    return SalesOutlier(
        deals=tuple(with_outlier),
        outlier_deal_id=outlier.deal_id,
        outlier_rep=CRM_OUTLIER_REP_NAME,
        top_reps_with_outlier=_top_reps(with_outlier, CRM_TOP_N),
        top_reps_without_outlier=without_outlier,
    )


def crm_deals_table(outlier: SalesOutlier) -> TableNeedle:
    return TableNeedle(
        schema_name=CRM_DEALS_SCHEMA,
        table_name=CRM_DEALS_TABLE,
        columns=CRM_DEALS_COLUMNS,
        rows=tuple(
            (deal.deal_id, deal.rep_name, deal.rep_email, deal.account_name, deal.days_ago, deal.amount_usd)
            for deal in outlier.deals
        ),
        date_column="closed_on",
    )


def build_slack_export() -> SlackExport:
    rng = random.Random(PACK_SEED + 3)
    users = tuple(_person("slack", index).name or "" for index in range(10))
    rows: list[tuple[Any, ...]] = []
    for _ in range(SLACK_NOISE_MESSAGE_COUNT):
        template = rng.choice(_SLACK_NOISE_TEMPLATES)
        text = template.format(
            account=rng.choice(_ACCOUNT_NAMES), hour=rng.randrange(9, 17), weekday=rng.choice(_WEEKDAYS)
        )
        rows.append((rng.choice(_SLACK_CHANNELS), 1 + rng.randrange(240), rng.choice(users), text))
    rows.append((SLACK_PRETAX_CHANNEL, SLACK_PRETAX_DAYS_AGO, users[0], SLACK_PRETAX_TEXT))

    unhappy = _ACCOUNT_NAMES[1:5]
    for account_index, account in enumerate(unhappy):
        for message in range(SLACK_UNHAPPY_THRESHOLD):
            days_ago = 10 + account_index * 20 + message * 15
            text = _SLACK_UNHAPPY_TEMPLATES[message].format(account=account)
            rows.append((SLACK_UNHAPPY_CHANNEL, days_ago, users[1 + message], text))
    # Near misses: two unhappy messages inside the window, and three that are too old to count.
    for message in range(SLACK_UNHAPPY_THRESHOLD - 1):
        rows.append(
            (
                SLACK_UNHAPPY_CHANNEL,
                30 + message * 30,
                users[4],
                _SLACK_UNHAPPY_TEMPLATES[message].format(account=_ACCOUNT_NAMES[5]),
            )
        )
    for message in range(SLACK_UNHAPPY_THRESHOLD):
        rows.append(
            (
                SLACK_UNHAPPY_CHANNEL,
                SLACK_UNHAPPY_WINDOW_DAYS + 20 + message * 10,
                users[5],
                _SLACK_UNHAPPY_TEMPLATES[message].format(account=_ACCOUNT_NAMES[6]),
            )
        )
    rows.sort(key=lambda row: (-row[1], row[0], row[3]))
    return SlackExport(
        table=TableNeedle(
            schema_name=SLACK_MESSAGES_SCHEMA,
            table_name=SLACK_MESSAGES_TABLE,
            columns=SLACK_MESSAGES_COLUMNS,
            rows=tuple(rows),
            date_column="ts",
        ),
        unhappy_accounts=tuple(unhappy),
    )


def build_account_health() -> AccountHealth:
    rng = random.Random(PACK_SEED + 4)
    rows: list[tuple[Any, ...]] = []
    at_risk: list[str] = []
    for index, name in enumerate(_ACCOUNT_NAMES[:ACCOUNT_COUNT]):
        # Three planted accounts sit above the threshold. One of them is also unhappy in Slack, so
        # the two branches of the churn-risk definition overlap and the union is smaller than the sum.
        if index in (2, 9, 13):
            score = 6 + rng.randrange(4)
        else:
            score = rng.randrange(CHURN_HEALTH_THRESHOLD + 1)
        rows.append((name, score, 1))
        if score > CHURN_HEALTH_THRESHOLD:
            at_risk.append(name)
    return AccountHealth(
        table=TableNeedle(
            schema_name=ACCOUNT_HEALTH_SCHEMA,
            table_name=ACCOUNT_HEALTH_TABLE,
            columns=ACCOUNT_HEALTH_COLUMNS,
            rows=tuple(rows),
            date_column="as_of",
        ),
        at_risk_accounts=tuple(at_risk),
    )
