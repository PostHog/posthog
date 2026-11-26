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

import uuid
import random
import hashlib
from collections import deque
from collections.abc import Collection, Iterable, Sequence
from typing import Any

from posthog.dataclasses import frozen

PACK_TOKEN = "evalpack"
PACK_EMAIL_DOMAIN = "example.com"
PACK_SEED = 20261029

# WAU_SPIKE: a sponsored video sends new users to the Hedgebox campaign landing page.
WAU_SPIKE_PERSON_COUNT = 200
WAU_SPIKE_DAYS_AGO = (10, 9, 8)
CAMPAIGN_PATH = "/mariustechtips/"
CAMPAIGN_URL = f"https://hedgebox.net{CAMPAIGN_PATH}"
CAMPAIGN_REFERRER = "https://www.youtube.com/@mariustechtips"
CAMPAIGN_REFERRING_DOMAIN = "www.youtube.com"
CAMPAIGN_UTM_SOURCE = "mariustechtips"
CAMPAIGN_ANNOTATION_CONTENT = "Marius Tech Tips sponsorship went live"
CAMPAIGN_ANNOTATION_DAYS_AGO = WAU_SPIKE_DAYS_AGO[0]
WAU_SPIKE_ARRIVAL_WEIGHTS = (0.7, 0.2, 0.1)
WAU_SPIKE_SIGNUP_SHARE = 0.85
WAU_SPIKE_RETURN_RATE = 0.5
WAU_SPIKE_RETURN_DECAY = 0.75
WAU_SPIKE_LAST_RETURN_DAYS_AGO = 3

# FLAT_WAU: steady members who hold weekly active users near one level over the whole history.
# Hedgebox grows every week, so without them any WAU question finds a real rise.
FLAT_WAU_WEEKLY_JITTER = 0.006
"""The planned level moves by at most twice this from one week to the next."""
FLAT_WAU_EXTRA_DAY_RATE = 0.13
"""With the one weekly visit, this gives about 1.9 active days a week, as Hedgebox users have."""
FLAT_WAU_PATHS = ("/", "/files/", "/files/", "/account/settings/")

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
# The last day of flag exposure events. The blocked cohort shares nothing from the block start through day 1.
SHARE_EXPOSURE_TO_DAYS_AGO = 4
SHARE_BLOCKED_SHARES_PER_DAY = 2

# SHARE_DAU: steady daily sharing with a known average. The Hedgebox generator can emit share events, but the
# seeded master data has none.
SHARE_DAU_PERSON_COUNT = 48
SHARE_DAU_DAILY_SHARERS = 12
SHARE_DAU_WINDOW_DAYS = 90

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

# MCP_TOOL_FAILURES: one tool starts to fail often in the last week, and the other tools never fail.
MCP_FAILING_TOOL = f"{PACK_TOKEN}-import"
MCP_FAILURE_WINDOW_DAYS = 28
MCP_FAILURE_RISE_DAYS = 7
MCP_FAILING_TOOL_CALLS_PER_SESSION = 3
# Every Nth call of the failing tool fails: 5% before the rise and about 33% during it.
MCP_FAILING_TOOL_BASELINE_EVERY = 20
MCP_FAILING_TOOL_RISE_EVERY = 3

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

# SLACK_PRETAX_NOTE: a Slack export with one finance note among noise.
SLACK_MESSAGES_SCHEMA = f"slack_messages_{PACK_TOKEN}"
SLACK_MESSAGES_TABLE = f"postgres_{SLACK_MESSAGES_SCHEMA}"
SLACK_MESSAGES_COLUMNS = ("channel", "ts", "user", "text")
SLACK_NOISE_MESSAGE_COUNT = 200
SLACK_PRETAX_CHANNEL = "#finance"
SLACK_PRETAX_TEXT = "reminder: paid_bill.amount_usd is pre-tax, finance reports post-tax (x1.08)"
SLACK_PRETAX_DAYS_AGO = 40
POST_TAX_MULTIPLIER = 1.08

# ORG_GRAIN_METRIC: an approved metric whose grain is the account, not the user.
ORG_GRAIN_METRIC_NAME = "avg_spend_per_account"
ORG_GRAIN_METRIC_DESCRIPTION = (
    "Average paid_bill spend per account over the trailing 30 days, pre-tax. "
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

BUSINESS_STANDARD_PLAN = "business/standard"
BUSINESS_ENTERPRISE_PLAN = "business/enterprise"
PERSONAL_FREE_PLAN = "personal/free"
PERSONAL_PRO_PLAN = "personal/pro"
_SEAT_PRICE_USD = {BUSINESS_STANDARD_PLAN: 10.0, BUSINESS_ENTERPRISE_PLAN: 20.0, PERSONAL_PRO_PLAN: 10.0}
ACCOUNT_ACTIVE_DAY_RATE = 0.6
"""The chance that a member of a planted account uses Hedgebox on a given day."""

# ACCOUNT_RENEWAL: a business account that shrank before its renewal. A question about the renewal names none of it.
RENEWAL_ACCOUNT_NAME = "Larkspur Engineering"
RENEWAL_START_MEMBERS = 10
RENEWAL_REMOVAL_DAYS_AGO = (40, 33, 26, 12)
RENEWAL_DOWNGRADE_DAYS_AGO = 21
RENEWAL_BILL_DAYS_AGO = (95, 65, 35, 5)
RENEWAL_WINDOW_DAYS = 100

# ACCOUNT_EXPANSION: a business account that doubled its seats through invites, but no invited member uses Hedgebox.
EXPANSION_ACCOUNT_NAME = "Wrenfield Robotics"
EXPANSION_CORE_MEMBERS = 5
EXPANSION_INVITE_DAYS_AGO = (52, 45, 38, 31, 24)
EXPANSION_BILL_DAYS_AGO = (80, 50, 20)
EXPANSION_WINDOW_DAYS = 90

# PREVIEW_LAUNCH: file previews that users adopt, while about a quarter of the PDF previews fail to render.
PREVIEW_FAILING_FILE_TYPE = "application/pdf"
PREVIEW_PDF_FAILURE_SHARE = 0.25
# The issue name, error type and value match the Hedgebox demo issue, so the planted errors join that issue when the
# case team has it.
PREVIEW_RENDER_ISSUE_NAME = "File preview render failure"
PREVIEW_RENDER_ISSUE_DESCRIPTION = (
    "Preview rendering fails for some uploaded PDFs, leaving customers unable to inspect files before sharing them."
)
PREVIEW_RENDER_ERROR_TYPE = "RenderError"
PREVIEW_RENDER_ERROR_VALUE = "Failed to render PDF preview"
PREVIEW_RENDER_FINGERPRINT = f"{PACK_TOKEN}-preview-render-pdf"
PREVIEW_RENDER_URL = "https://app.hedgebox.test/app/files"
PREVIEW_RENDER_SOURCE = "https://app.hedgebox.test/static/js/file-preview.js"
PREVIEW_RENDER_FUNCTION = "renderPdfPreview"

# UPGRADE_BANNER: an experiment whose test banner doubles upgrades, but most of the extra upgraders downgrade again.
UPGRADE_BANNER_EXPERIMENT_NAME = "Pro plan banner"
UPGRADE_BANNER_FLAG_KEY = f"pro-plan-banner-{PACK_TOKEN}"
UPGRADE_BANNER_START_DAYS_AGO = 21
UPGRADE_BANNER_PERSONS_PER_VARIANT = 150
UPGRADE_BANNER_DOWNGRADE_WITHIN_DAYS = 7
UPGRADE_BANNER_RETURN_RATE = 0.3
UPGRADE_BANNER_METRIC: dict[str, Any] = {
    "kind": "ExperimentMetric",
    "metric_type": "funnel",
    "uuid": "6f1d2c3a-4b5e-4f60-8a71-92b3c4d5e6f7",
    "name": "Upgrade to a paid plan",
    "series": [{"kind": "EventsNode", "event": "upgraded_plan"}],
    "goal": "increase",
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


# Ingestion copies these event properties onto the person as `$initial_<name>` the first time it sees each one.
_INITIAL_PROPERTY_KEYS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "gclid",
    "fbclid",
    "$browser",
    "$browser_version",
    "$device_type",
    "$current_url",
    "$pathname",
    "$os",
    "$referring_domain",
    "$referrer",
)


def initial_person_properties(events: Sequence[PlantedEvent]) -> dict[str, dict[str, Any]]:
    """The `$initial_*` properties that ingestion sets on each distinct id from its earliest events."""
    initial: dict[str, dict[str, Any]] = {}
    for event in sorted(events, key=lambda event: event.minute_of_day - event.days_ago * 24 * 60):
        person = initial.setdefault(event.distinct_id, {})
        for key in _INITIAL_PROPERTY_KEYS:
            value = event.properties.get(key)
            if value is not None:
                person.setdefault(f"$initial_{key.removeprefix('$')}", value)
    return initial


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


_WEB_CLIENTS = (
    ("Chrome", "Mac OS X", "Desktop"),
    ("Chrome", "Windows", "Desktop"),
    ("Safari", "iOS", "Mobile"),
    ("Chrome", "Android", "Mobile"),
    ("Firefox", "Linux", "Desktop"),
    ("Microsoft Edge", "Windows", "Desktop"),
    ("Safari", "Mac OS X", "Desktop"),
)
_WEB_COUNTRIES = ("US", "US", "US", "GB", "DE", "CA", "FR", "IN", "BR", "AU")
_WEB_LIB_VERSION = "1.298.0"


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _web_client(rng: random.Random) -> dict[str, Any]:
    """The properties the web SDK sends from one device, so planted users look like Hedgebox users."""
    browser, os, device_type = rng.choice(_WEB_CLIENTS)
    return {
        "$lib": "web",
        "$lib_version": _WEB_LIB_VERSION,
        "$host": "hedgebox.net",
        "$browser": browser,
        "$os": os,
        "$device_type": device_type,
        "$geoip_country_code": rng.choice(_WEB_COUNTRIES),
        "$browser_language": "en-US",
        "$device_id": _uuid(rng),
    }


def _web_event(client: dict[str, Any], pathname: str, session_id: str, **extra: Any) -> dict[str, Any]:
    return {
        **client,
        "$current_url": f"https://hedgebox.net{pathname}",
        "$pathname": pathname,
        "$session_id": session_id,
        "$referrer": "$direct",
        **extra,
    }


def _person(prefix: str, index: int) -> PlantedPerson:
    first = _FIRST_NAMES[index % len(_FIRST_NAMES)]
    last = _LAST_NAMES[(index // len(_FIRST_NAMES)) % len(_LAST_NAMES)]
    distinct_id = f"{PACK_TOKEN}-{prefix}-{index + 1:03d}"
    return PlantedPerson(distinct_id=distinct_id, email=f"{distinct_id}@{PACK_EMAIL_DOMAIN}", name=f"{first} {last}")


def build_wau_spike() -> EventNeedle:
    rng = random.Random(PACK_SEED + 5)
    persons = tuple(_person("campaign", index) for index in range(WAU_SPIKE_PERSON_COUNT))
    landing = {
        "$current_url": f"{CAMPAIGN_URL}?utm_source={CAMPAIGN_UTM_SOURCE}",
        "$referrer": CAMPAIGN_REFERRER,
        "$referring_domain": CAMPAIGN_REFERRING_DOMAIN,
        "utm_source": CAMPAIGN_UTM_SOURCE,
    }
    events: list[PlantedEvent] = []

    def add(event: str, person: PlantedPerson, days_ago: int, minute: int, properties: dict[str, Any]) -> None:
        events.append(
            PlantedEvent(
                event=event,
                distinct_id=person.distinct_id,
                days_ago=days_ago,
                minute_of_day=minute,
                properties=properties,
            )
        )

    for person in persons:
        client = _web_client(rng)
        arrival = rng.choices(WAU_SPIKE_DAYS_AGO, weights=WAU_SPIKE_ARRIVAL_WEIGHTS)[0]
        # Most viewers watch the video in the evening, so arrivals peak late in the day.
        minute = min(1400, int(rng.triangular(240, 1440, 1140)))
        session = _uuid(rng)
        add("$pageview", person, arrival, minute, _web_event(client, CAMPAIGN_PATH, session, **landing))
        if rng.random() >= WAU_SPIKE_SIGNUP_SHARE:
            continue
        signup_minute = minute + rng.randint(1, 12)
        add("signed_up", person, arrival, signup_minute, _web_event(client, "/signup/", session, from_invite=False))
        add("logged_in", person, arrival, signup_minute + 1, _web_event(client, "/files/", session))
        for day in range(arrival - 1, WAU_SPIKE_LAST_RETURN_DAYS_AGO - 1, -1):
            if rng.random() >= WAU_SPIKE_RETURN_RATE * WAU_SPIKE_RETURN_DECAY ** (arrival - 1 - day):
                continue
            minute = rng.randrange(360, 1380)
            session = _uuid(rng)
            add("logged_in", person, day, minute, _web_event(client, "/login/", session))
            add("$pageview", person, day, minute + 1, _web_event(client, "/files/", session))
            if rng.random() < 0.3:
                upload = _web_event(
                    client, "/files/", session, file_type="image/png", file_size_b=rng.randrange(10**5, 10**7)
                )
                add(UPLOAD_EVENT, person, day, minute + 3, upload)
    return EventNeedle(name="wau_spike", persons=persons, events=tuple(events))


def rolling_weekly_actives(daily_active: Sequence[Collection[str]]) -> list[int]:
    """Users active in the 7 days that end ``index`` days ago, as PostHog's weekly active math counts them."""
    return [len(set().union(*daily_active[day : day + 7])) for day in range(len(daily_active))]


def _flat_wau_targets(organic: Sequence[int], rng: random.Random) -> list[int]:
    knots = [rng.uniform(-FLAT_WAU_WEEKLY_JITTER, FLAT_WAU_WEEKLY_JITTER) for _ in range(len(organic) // 7 + 2)]
    jitter = [knots[day // 7] + (knots[day // 7 + 1] - knots[day // 7]) * (day % 7) / 7 for day in range(len(organic))]
    level = max(count / (1 + jitter[day]) for day, count in enumerate(organic))
    return [max(count, round(level * (1 + jitter[day]))) for day, count in enumerate(organic)]


def build_flat_wau(daily_active: Sequence[Collection[str]], latest_minute: int) -> EventNeedle:
    """Plant members whose weekly visits fill the gap between the organic WAU and a level line.

    ``daily_active[day]`` holds the users active ``day`` days ago. Each member is active once in
    every 7 days from the first day to the last day, so a member counts in exactly the windows that
    overlap that range. A member starts when the gap grows and stops when the gap shrinks.
    """
    rng = random.Random(PACK_SEED + 6)
    organic = rolling_weekly_actives(daily_active)
    if not organic:
        return EventNeedle(name="flat_wau", persons=(), events=())
    gap = [target - count for target, count in zip(_flat_wau_targets(organic, rng), organic)]
    # Per member: the first (oldest) active day and the last active day, both as days ago.
    spans: list[list[int]] = []
    live: deque[int] = deque()
    oldest = len(organic) - 1
    for day in range(oldest, -1, -1):
        # A member whose last day is ``day + 7`` leaves this window. It must have started 7 days earlier, or
        # its single weekly visit could fall inside this window.
        while len(live) > gap[day] and day < oldest and spans[live[0]][0] >= day + 7:
            spans[live.popleft()][1] = day + 7
        while len(live) < gap[day]:
            live.append(len(spans))
            spans.append([day, 0])
    for index in live:
        spans[index][1] = spans[index][0] % 7

    persons = tuple(_person("member", index) for index in range(len(spans)))
    events: list[PlantedEvent] = []
    for person, (first, last) in zip(persons, spans):
        client = _web_client(rng)
        weekly = set(range(first, last - 1, -7)) | {last}
        extra = {day for day in range(max(last, 1), first) if rng.random() < FLAT_WAU_EXTRA_DAY_RATE}
        for day in sorted(weekly | extra, reverse=True):
            minute = rng.randrange(max(1, latest_minute)) if day == 0 else rng.randrange(1440)
            properties = _web_event(client, rng.choice(FLAT_WAU_PATHS), _uuid(rng))
            events.append(
                PlantedEvent(
                    event="$pageview",
                    distinct_id=person.distinct_id,
                    days_ago=day,
                    minute_of_day=minute,
                    properties=properties,
                )
            )
    return EventNeedle(name="flat_wau", persons=persons, events=tuple(events))


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
                if SHARE_EXPOSURE_TO_DAYS_AGO <= day <= SHARE_BLOCK_FROM_DAYS_AGO:
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


def build_share_dau() -> EventNeedle:
    """Each person shares on every fourth day, offset by index, so the same number of people share each day."""
    persons = tuple(_person("dailysharer", index) for index in range(SHARE_DAU_PERSON_COUNT))
    cycle = SHARE_DAU_PERSON_COUNT // SHARE_DAU_DAILY_SHARERS
    events = tuple(
        PlantedEvent(
            event=SHARE_EVENT,
            distinct_id=person.distinct_id,
            days_ago=day,
            minute_of_day=60 + (index * 17) % 1200,
            properties={"file_type": "application/pdf", "file_size_b": 524_288},
        )
        for day in range(SHARE_DAU_WINDOW_DAYS, 0, -1)
        for index, person in enumerate(persons)
        if (index + day) % cycle == 0
    )
    return EventNeedle(name="share_dau", persons=persons, events=events)


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


def build_mcp_tool_failures() -> EventNeedle:
    persons = tuple(_person("toolagent", index) for index in range(MCP_AGENT_USER_COUNT))
    tools = (*MCP_BASE_TOOLS, *([MCP_FAILING_TOOL] * MCP_FAILING_TOOL_CALLS_PER_SESSION))
    events: list[PlantedEvent] = []
    failing_calls = 0
    for day in range(MCP_FAILURE_WINDOW_DAYS, 0, -1):
        every = MCP_FAILING_TOOL_RISE_EVERY if day <= MCP_FAILURE_RISE_DAYS else MCP_FAILING_TOOL_BASELINE_EVERY
        for session in range(MCP_SESSIONS_PER_DAY):
            person = persons[(day * MCP_SESSIONS_PER_DAY + session) % len(persons)]
            session_id = f"{PACK_TOKEN}-failures-{day:03d}-{session}"
            for step, tool in enumerate(tools):
                failed = False
                if tool == MCP_FAILING_TOOL:
                    failing_calls += 1
                    failed = failing_calls % every == 0
                events.append(
                    PlantedEvent(
                        event=MCP_TOOL_CALL_EVENT,
                        distinct_id=person.distinct_id,
                        days_ago=day,
                        minute_of_day=120 + session * 240 + step,
                        properties={
                            "tool_name": tool,
                            "$mcp_tool_name": tool,
                            "$mcp_duration_ms": 400,
                            "$mcp_is_error": failed,
                            "$session_id": session_id,
                        },
                    )
                )
    return EventNeedle(name="mcp_tool_failures", persons=persons, events=tuple(events))


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

    rows.sort(key=lambda row: (-row[1], row[0], row[3]))
    return SlackExport(
        table=TableNeedle(
            schema_name=SLACK_MESSAGES_SCHEMA,
            table_name=SLACK_MESSAGES_TABLE,
            columns=SLACK_MESSAGES_COLUMNS,
            rows=tuple(rows),
            date_column="ts",
        ),
    )


def stable_share(key: str) -> float:
    """A value in [0, 1) that depends only on ``key``, so a planted choice does not depend on the order of rows."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0x1_0000_0000


@frozen
class PlantedAccount:
    group_key: str
    properties: dict[str, Any]
    """The account group properties at the end of the window, with the keys that the Hedgebox simulation sets."""


@frozen
class AccountNeedle:
    account: PlantedAccount
    members: EventNeedle


_FILE_TYPES = ("image/png", "image/jpeg", "application/pdf", "text/plain")
_MEMBER_FILE_EVENTS = (UPLOAD_EVENT, "downloaded_file", SHARE_EVENT)


def _account_properties(account_key: str) -> dict[str, Any]:
    return {"$group_0": account_key, "$groups": {"account": account_key}}


def _member_days(
    rng: random.Random, member: PlantedPerson, account_key: str, client: dict[str, Any], days: Iterable[int]
) -> list[PlantedEvent]:
    """On each active day, the member logs in, opens the files page, and does one file action."""
    group = _account_properties(account_key)
    events: list[PlantedEvent] = []
    for day in days:
        if rng.random() >= ACCOUNT_ACTIVE_DAY_RATE:
            continue
        minute = rng.randrange(480, 1080)
        session = _uuid(rng)
        file_action = rng.choice(_MEMBER_FILE_EVENTS)
        file_properties = {"file_type": rng.choice(_FILE_TYPES), "file_size_b": rng.randrange(10**5, 5 * 10**7)}
        for offset, (event, pathname, extra) in enumerate(
            (("logged_in", "/login/", {}), ("$pageview", "/files/", {}), (file_action, "/files/", file_properties))
        ):
            events.append(
                PlantedEvent(
                    event=event,
                    distinct_id=member.distinct_id,
                    days_ago=day,
                    minute_of_day=minute + offset,
                    properties=_web_event(client, pathname, session, **group, **extra),
                )
            )
    return events


def _bill(payer: PlantedPerson, days_ago: int, *, plan: str, seats: int, account_key: str | None) -> PlantedEvent:
    # Hedgebox bills from its server, so a bill carries the Python library and no browser properties.
    group = _account_properties(account_key) if account_key else {}
    return PlantedEvent(
        event="paid_bill",
        distinct_id=payer.distinct_id,
        days_ago=days_ago,
        minute_of_day=60,
        properties={"$lib": "posthog-python", "amount_usd": _SEAT_PRICE_USD[plan] * seats, "plan": plan, **group},
    )


def _account(key: str, name: str, *, plan: str, team_size: int, events: Sequence[PlantedEvent]) -> PlantedAccount:
    uploads = [event for event in events if event.event == UPLOAD_EVENT]
    # Hedgebox stores the byte sum of the account's files in used_mb, despite the name.
    return PlantedAccount(
        group_key=key,
        properties={
            "name": name,
            "industry": "technology",
            "plan": plan,
            "team_size": team_size,
            "file_count": len(uploads),
            "used_mb": sum(event.properties["file_size_b"] for event in uploads),
        },
    )


def build_renewal_account() -> AccountNeedle:
    rng = random.Random(PACK_SEED + 7)
    key = _uuid(rng)
    group = _account_properties(key)
    members = tuple(_person("larkspur", index) for index in range(RENEWAL_START_MEMBERS))
    admin = members[0]
    clients = {member.distinct_id: _web_client(rng) for member in members}
    # The newest members leave first. The admin removes the others, so the admin stays.
    removal_day = {member.distinct_id: day for member, day in zip(reversed(members), RENEWAL_REMOVAL_DAYS_AGO)}
    events: list[PlantedEvent] = []
    for member in members:
        # A removed member is active up to the day before the removal.
        last_day = removal_day.get(member.distinct_id, 0)
        events += _member_days(rng, member, key, clients[member.distinct_id], range(RENEWAL_WINDOW_DAYS, last_day, -1))
    admin_client = clients[admin.distinct_id]
    for day in RENEWAL_REMOVAL_DAYS_AGO:
        events.append(
            PlantedEvent(
                event="removed_team_member",
                distinct_id=admin.distinct_id,
                days_ago=day,
                minute_of_day=600,
                properties=_web_event(admin_client, "/account/team/", _uuid(rng), **group),
            )
        )
    events.append(
        PlantedEvent(
            event="downgraded_plan",
            distinct_id=admin.distinct_id,
            days_ago=RENEWAL_DOWNGRADE_DAYS_AGO,
            minute_of_day=610,
            properties=_web_event(
                admin_client,
                "/account/billing/",
                _uuid(rng),
                previous_plan=BUSINESS_ENTERPRISE_PLAN,
                new_plan=BUSINESS_STANDARD_PLAN,
                **group,
            ),
        )
    )
    for day in RENEWAL_BILL_DAYS_AGO:
        plan = BUSINESS_ENTERPRISE_PLAN if day > RENEWAL_DOWNGRADE_DAYS_AGO else BUSINESS_STANDARD_PLAN
        seats = RENEWAL_START_MEMBERS - sum(removal > day for removal in RENEWAL_REMOVAL_DAYS_AGO)
        events.append(_bill(admin, day, plan=plan, seats=seats, account_key=key))
    return AccountNeedle(
        account=_account(
            key,
            RENEWAL_ACCOUNT_NAME,
            plan=BUSINESS_STANDARD_PLAN,
            team_size=RENEWAL_START_MEMBERS - len(RENEWAL_REMOVAL_DAYS_AGO),
            events=events,
        ),
        members=EventNeedle(name="renewal_account", persons=members, events=tuple(events)),
    )


def build_expansion_account() -> AccountNeedle:
    rng = random.Random(PACK_SEED + 8)
    key = _uuid(rng)
    group = _account_properties(key)
    team_size = EXPANSION_CORE_MEMBERS + len(EXPANSION_INVITE_DAYS_AGO)
    members = tuple(_person("wrenfield", index) for index in range(team_size))
    core, invited = members[:EXPANSION_CORE_MEMBERS], members[EXPANSION_CORE_MEMBERS:]
    admin = core[0]
    clients = {member.distinct_id: _web_client(rng) for member in members}
    events: list[PlantedEvent] = []
    for member in core:
        events += _member_days(rng, member, key, clients[member.distinct_id], range(EXPANSION_WINDOW_DAYS, 0, -1))
    for member, day in zip(invited, EXPANSION_INVITE_DAYS_AGO):
        events.append(
            PlantedEvent(
                event="invited_team_member",
                distinct_id=admin.distinct_id,
                days_ago=day,
                minute_of_day=600,
                properties=_web_event(clients[admin.distinct_id], "/account/team/", _uuid(rng), **group),
            )
        )
        # The invited member joins on the day of the invite and never comes back.
        session = _uuid(rng)
        join_steps: tuple[tuple[str, str, dict[str, Any]], ...] = (
            ("$pageview", f"/invite/{_uuid(rng)}/", {}),
            ("signed_up", "/signup/", {"from_invite": True}),
            ("logged_in", "/files/", {}),
            ("$pageview", "/files/", {}),
        )
        for offset, (event, pathname, extra) in enumerate(join_steps):
            events.append(
                PlantedEvent(
                    event=event,
                    distinct_id=member.distinct_id,
                    days_ago=day,
                    minute_of_day=640 + offset,
                    properties=_web_event(clients[member.distinct_id], pathname, session, **group, **extra),
                )
            )
    for day in EXPANSION_BILL_DAYS_AGO:
        seats = EXPANSION_CORE_MEMBERS + sum(invite > day for invite in EXPANSION_INVITE_DAYS_AGO)
        events.append(_bill(admin, day, plan=BUSINESS_STANDARD_PLAN, seats=seats, account_key=key))
    return AccountNeedle(
        account=_account(key, EXPANSION_ACCOUNT_NAME, plan=BUSINESS_STANDARD_PLAN, team_size=team_size, events=events),
        members=EventNeedle(name="expansion_account", persons=members, events=tuple(events)),
    )


@frozen
class PreviewLaunchSpec:
    """The file preview adoption, with one file type per preview and render errors for a share of one type."""

    adoption: AdoptionSpec
    file_types: tuple[str, ...]
    failing_file_type: str
    failure_share: float

    def file_type_for(self, distinct_id: str, days_ago: int) -> str:
        return self.file_types[int(stable_share(f"{distinct_id}:{days_ago}:type") * len(self.file_types))]

    def fails(self, distinct_id: str, days_ago: int) -> bool:
        return (
            self.file_type_for(distinct_id, days_ago) == self.failing_file_type
            and stable_share(f"{distinct_id}:{days_ago}:render") < self.failure_share
        )


PREVIEW_LAUNCH = PreviewLaunchSpec(
    adoption=PREVIEW_ADOPTION,
    file_types=_FILE_TYPES,
    failing_file_type=PREVIEW_FAILING_FILE_TYPE,
    failure_share=PREVIEW_PDF_FAILURE_SHARE,
)


@frozen
class BannerArm:
    variant: str
    upgraders: int
    downgraders: int
    """Upgraders who downgrade again within ``UPGRADE_BANNER_DOWNGRADE_WITHIN_DAYS`` days of the upgrade."""


# About 8% of control and 18% of test upgrade. After the early downgrades, about 7% and 8% stay upgraded.
UPGRADE_BANNER_ARMS = (
    BannerArm(variant="control", upgraders=12, downgraders=1),
    BannerArm(variant="test", upgraders=27, downgraders=15),
)


def build_upgrade_banner() -> FlagNeedle:
    rng = random.Random(PACK_SEED + 9)
    persons: list[PlantedPerson] = []
    events: list[PlantedEvent] = []
    for arm in UPGRADE_BANNER_ARMS:
        flag = {f"$feature/{UPGRADE_BANNER_FLAG_KEY}": arm.variant}
        exposure = {"$feature_flag": UPGRADE_BANNER_FLAG_KEY, "$feature_flag_response": arm.variant, **flag}
        cohort = tuple(_person(f"banner{arm.variant}", index) for index in range(UPGRADE_BANNER_PERSONS_PER_VARIANT))
        persons += cohort
        for index, person in enumerate(cohort):
            client = _web_client(rng)
            # Exposures start the day after the experiment starts and run to yesterday. A downgrader is exposed
            # early enough for the upgrade, up to 2 days later, and the downgrade, up to 6 days after that.
            last_exposure = UPGRADE_BANNER_DOWNGRADE_WITHIN_DAYS + 2 if index < arm.downgraders else 1
            exposed = rng.randint(last_exposure, UPGRADE_BANNER_START_DAYS_AGO - 1)
            visits = [exposed, *(day for day in range(exposed - 1, 0, -1) if rng.random() < UPGRADE_BANNER_RETURN_RATE)]
            for day in visits:
                minute = rng.randrange(480, 1200)
                session = _uuid(rng)
                steps = [("logged_in", "/login/", flag), ("$pageview", "/files/", flag)]
                if day == exposed:
                    steps.insert(1, ("$feature_flag_called", "/files/", exposure))
                for offset, (event, pathname, extra) in enumerate(steps):
                    events.append(
                        PlantedEvent(
                            event=event,
                            distinct_id=person.distinct_id,
                            days_ago=day,
                            minute_of_day=minute + offset,
                            properties=_web_event(client, pathname, session, **extra),
                        )
                    )
            if index >= arm.upgraders:
                continue
            # Plan changes happen late in the day, after the day's exposure.
            upgraded = max(1, exposed - rng.randint(0, 2))
            plan_changes = [(upgraded, PERSONAL_FREE_PLAN, PERSONAL_PRO_PLAN)]
            if index < arm.downgraders:
                downgraded = upgraded - rng.randint(2, UPGRADE_BANNER_DOWNGRADE_WITHIN_DAYS - 1)
                plan_changes.append((downgraded, PERSONAL_PRO_PLAN, PERSONAL_FREE_PLAN))
            for day, previous_plan, new_plan in plan_changes:
                events.append(
                    PlantedEvent(
                        event="upgraded_plan" if new_plan == PERSONAL_PRO_PLAN else "downgraded_plan",
                        distinct_id=person.distinct_id,
                        days_ago=day,
                        minute_of_day=1300,
                        properties=_web_event(
                            client,
                            "/account/billing/",
                            _uuid(rng),
                            previous_plan=previous_plan,
                            new_plan=new_plan,
                            **flag,
                        ),
                    )
                )
            events.append(_bill(person, upgraded, plan=PERSONAL_PRO_PLAN, seats=1, account_key=None))
    return FlagNeedle(
        key=UPGRADE_BANNER_FLAG_KEY,
        variants=tuple(arm.variant for arm in UPGRADE_BANNER_ARMS),
        events=EventNeedle(name="upgrade_banner", persons=tuple(persons), events=tuple(events)),
    )
