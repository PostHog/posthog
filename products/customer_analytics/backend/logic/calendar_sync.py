from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Any

from django.db.models import Prefetch, Q
from django.utils import timezone

import requests
import structlog

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration, OauthIntegration
from posthog.models.team import Team

from products.customer_analytics.backend.logic.email_account_matching import match_accounts_for_emails
from products.customer_analytics.backend.models import Account, Meeting, MeetingParticipant, MeetingStatus

logger = structlog.get_logger(__name__)

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
BACKFILL_DAYS = 365
PAGE_SIZE = 250
SYNC_TOKEN_CONFIG_KEY = "calendar_sync_token"
SYNC_STARTED_AT_CONFIG_KEY = "calendar_sync_started_at"
LAST_SYNCED_AT_CONFIG_KEY = "calendar_last_synced_at"
# Matches the sync activity's start_to_close timeout: past this, an unfinished run is dead.
SYNC_STALE_AFTER = timedelta(minutes=30)

PERSON_EMAIL_LOOKUP_QUERY = """
SELECT id, properties.email
FROM persons
WHERE lower(properties.email) IN {emails}
ORDER BY is_identified DESC, created_at ASC, id ASC
"""


class SyncTokenExpired(Exception):
    pass


class CalendarSyncError(Exception):
    pass


@dataclass
class CalendarSyncCounts:
    fetched: int = 0
    upserted: int = 0
    cancelled: int = 0
    skipped: int = 0
    matched: int = 0
    unmatched_emails: set[str] = field(default_factory=set)


def sync_calendar_integration(integration_id: int, team_id: int) -> CalendarSyncCounts:
    """Sync one connected Google Calendar into customer_analytics meetings.

    First run pulls BACKFILL_DAYS of history plus all future events; later runs are
    incremental via the stored syncToken. A stale token (HTTP 410) drops the cursor
    and re-lists the whole window in the same run.
    """
    integration = Integration.objects.get(id=integration_id, team_id=team_id, kind="google-calendar")
    team = integration.team
    access_token = _get_fresh_access_token(integration)
    connected_email = (integration.config or {}).get("email", "")
    internal_domain = _domain_of(connected_email)

    integration.config[SYNC_STARTED_AT_CONFIG_KEY] = timezone.now().isoformat()
    integration.save(update_fields=["config"])

    counts = CalendarSyncCounts()
    sync_token = (integration.config or {}).get(SYNC_TOKEN_CONFIG_KEY)
    try:
        next_sync_token = _sync_events(team, access_token, sync_token, internal_domain, counts)
    except SyncTokenExpired:
        next_sync_token = _sync_events(team, access_token, None, internal_domain, counts)

    integration.config[SYNC_TOKEN_CONFIG_KEY] = next_sync_token
    integration.config[LAST_SYNCED_AT_CONFIG_KEY] = timezone.now().isoformat()
    integration.save(update_fields=["config"])
    return counts


def _sync_events(
    team: Team, access_token: str, sync_token: str | None, internal_domain: str, counts: CalendarSyncCounts
) -> str:
    params: dict[str, Any] = {"singleEvents": "true", "showDeleted": "true", "maxResults": PAGE_SIZE}
    if sync_token:
        params["syncToken"] = sync_token
    else:
        params["timeMin"] = (timezone.now() - timedelta(days=BACKFILL_DAYS)).isoformat()

    next_sync_token = ""
    page_token: str | None = None
    while True:
        page_params = {**params, **({"pageToken": page_token} if page_token else {})}
        response = requests.get(
            EVENTS_URL, params=page_params, headers={"Authorization": f"Bearer {access_token}"}, timeout=30
        )
        if response.status_code == 410:
            raise SyncTokenExpired
        if response.status_code != 200:
            raise CalendarSyncError(f"Google Calendar API returned {response.status_code}: {response.text[:200]}")

        payload = response.json()
        events = payload.get("items", [])
        counts.fetched += len(events)
        _process_events(team, events, internal_domain, counts)

        page_token = payload.get("nextPageToken")
        if not page_token:
            next_sync_token = payload.get("nextSyncToken", "")
            break
    return next_sync_token


def _process_events(team: Team, events: list[dict], internal_domain: str, counts: CalendarSyncCounts) -> None:
    to_upsert: list[dict] = []
    for event in events:
        if event.get("status") == "cancelled":
            _mark_cancelled(team, event, counts)
            continue
        parsed = (
            None if event.get("visibility") in ("private", "confidential") else _parse_event(event, internal_domain)
        )
        if parsed is None:
            # A stored event that stopped passing the filters (made private, external
            # attendee removed) must disappear, not linger with stale data.
            _delete_filtered_out(team, event)
            counts.skipped += 1
            continue
        to_upsert.append(parsed)

    if not to_upsert:
        return

    external_emails = {p["email"] for parsed in to_upsert for p in parsed["participants"] if not p["is_internal"]}
    accounts_by_email = _match_accounts_for_emails(team, sorted(external_emails))
    all_emails = {p["email"] for parsed in to_upsert for p in parsed["participants"]}
    person_uuid_by_email = _person_uuids_by_email(team, sorted(all_emails))

    for parsed in to_upsert:
        account = next(
            (accounts_by_email[p["email"]] for p in parsed["participants"] if p["email"] in accounts_by_email),
            None,
        )
        if account is not None:
            counts.matched += 1
        else:
            counts.unmatched_emails.update(p["email"] for p in parsed["participants"] if not p["is_internal"])
        _upsert_meeting(team, parsed, account, person_uuid_by_email)
        counts.upserted += 1


def _parse_event(event: dict, internal_domain: str) -> dict | None:
    ical_uid = event.get("iCalUID")
    start = _parse_when(event.get("start"))
    if not ical_uid or start is None:
        return None

    attendees = event.get("attendees") or []
    organizer_email = ((event.get("organizer") or {}).get("email") or "").lower()
    participants = []
    seen_emails = set()
    for attendee in attendees:
        email = (attendee.get("email") or "").lower()
        if not email or "@" not in email or attendee.get("resource") or email in seen_emails:
            continue
        # Rooms and shared calendars are invitees too, but they aren't people.
        if email.endswith("group.calendar.google.com") or email.endswith("resource.calendar.google.com"):
            continue
        seen_emails.add(email)
        participants.append(
            {
                "email": email,
                "display_name": attendee.get("displayName") or "",
                "response_status": _response_status(attendee.get("responseStatus")),
                "is_organizer": email == organizer_email,
                "is_internal": _domain_of(email) == internal_domain,
            }
        )

    # A meeting with no external attendee is internal business, not a customer touchpoint.
    if not any(not p["is_internal"] for p in participants):
        return None

    return {
        "ical_uid": ical_uid,
        "recurrence_instance_id": _recurrence_instance_id(event),
        "title": event.get("summary") or "",
        "description": event.get("description") or "",
        "start_time": start,
        "end_time": _parse_when(event.get("end")),
        "organizer_email": organizer_email,
        "meet_code": (event.get("conferenceData") or {}).get("conferenceId") or "",
        "status": event.get("status") if event.get("status") in MeetingStatus.values else MeetingStatus.CONFIRMED,
        "participants": participants,
    }


def _upsert_meeting(team: Team, parsed: dict, account: Account | None, person_uuid_by_email: dict[str, str]) -> None:
    defaults = {
        "title": parsed["title"],
        "description": parsed["description"],
        "start_time": parsed["start_time"],
        "end_time": parsed["end_time"],
        "organizer_email": parsed["organizer_email"],
        "meet_code": parsed["meet_code"],
        "status": parsed["status"],
    }
    if account is not None:
        defaults["account"] = account

    meeting, _created = Meeting.objects.for_team(team.id).update_or_create(
        team_id=team.id,
        ical_uid=parsed["ical_uid"],
        recurrence_instance_id=parsed["recurrence_instance_id"],
        defaults=defaults,
    )
    for participant in parsed["participants"]:
        MeetingParticipant.objects.for_team(team.id).update_or_create(
            team_id=team.id,
            meeting=meeting,
            email=participant["email"],
            defaults={
                "display_name": participant["display_name"],
                "response_status": participant["response_status"],
                "is_organizer": participant["is_organizer"],
                "person_id": person_uuid_by_email.get(participant["email"]),
            },
        )
    current_emails = [participant["email"] for participant in parsed["participants"]]
    MeetingParticipant.objects.for_team(team.id).filter(meeting=meeting).exclude(email__in=current_emails).delete()


def _delete_filtered_out(team: Team, event: dict) -> None:
    ical_uid = event.get("iCalUID")
    if not ical_uid:
        return
    Meeting.objects.for_team(team.id).filter(
        ical_uid=ical_uid, recurrence_instance_id=_recurrence_instance_id(event)
    ).delete()


def _mark_cancelled(team: Team, event: dict, counts: CalendarSyncCounts) -> None:
    ical_uid = event.get("iCalUID")
    if not ical_uid:
        return
    updated = (
        Meeting.objects.for_team(team.id)
        .filter(ical_uid=ical_uid, recurrence_instance_id=_recurrence_instance_id(event))
        .update(status=MeetingStatus.CANCELLED)
    )
    counts.cancelled += updated


def rematch_account_meetings(team_id: int, account_id: str) -> int:
    account = Account.objects.for_team(team_id).select_related("team").filter(id=account_id).first()
    if account is None:
        return 0

    known_emails = set(account.properties.known_emails)
    email_domains = {domain.removeprefix("@").lower() for domain in account.properties.email_domains if domain}
    if not known_emails and not email_domains:
        return 0

    participant_filter = Q(email__in=known_emails)
    for domain in email_domains:
        participant_filter |= Q(email__iendswith=f"@{domain}")

    candidate_meeting_ids = list(
        MeetingParticipant.objects.for_team(team_id)
        .filter(participant_filter, meeting__account__isnull=True)
        .values_list("meeting_id", flat=True)
        .distinct()
    )
    if not candidate_meeting_ids:
        return 0

    meetings = list(
        Meeting.objects.for_team(team_id)
        .filter(id__in=candidate_meeting_ids, account__isnull=True)
        .prefetch_related(
            Prefetch(
                "participants",
                queryset=MeetingParticipant.objects.for_team(team_id).order_by("created_at", "id"),
            )
        )
    )
    emails = sorted({participant.email for meeting in meetings for participant in meeting.participants.all()})
    accounts_by_email = _match_accounts_for_emails(account.team, emails)

    meeting_ids_to_attach = []
    for meeting in meetings:
        matched_account_ids = {
            matched_account.id
            for participant in meeting.participants.all()
            if (matched_account := accounts_by_email.get(participant.email)) is not None
        }
        if matched_account_ids == {account.id}:
            meeting_ids_to_attach.append(meeting.id)

    if not meeting_ids_to_attach:
        return 0
    return (
        Meeting.objects.for_team(team_id)
        .filter(id__in=meeting_ids_to_attach, account__isnull=True)
        .update(account=account)
    )


def _match_accounts_for_emails(team: Team, emails: list[str]) -> dict[str, Account]:
    return {email: match.account for email, match in match_accounts_for_emails(team, emails).items()}


def _person_uuids_by_email(team: Team, emails: list[str]) -> dict[str, str]:
    if not emails:
        return {}
    # Deferred: hogql.query pulls the whole query-runner layer into module import.
    from posthog.hogql import ast  # noqa: PLC0415
    from posthog.hogql.query import execute_hogql_query  # noqa: PLC0415

    with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY):
        response = execute_hogql_query(
            PERSON_EMAIL_LOOKUP_QUERY,
            placeholders={"emails": ast.Constant(value=emails)},
            team=team,
            query_type="customer_analytics_calendar_person_lookup",
        )
    email_to_uuid: dict[str, str] = {}
    for person_uuid, prop_email in response.results or []:
        lower = (prop_email or "").lower()
        if lower and lower not in email_to_uuid:
            email_to_uuid[lower] = str(person_uuid)
    return email_to_uuid


def _get_fresh_access_token(integration: Integration) -> str:
    oauth = OauthIntegration(integration)
    if integration.errors != ERROR_TOKEN_REFRESH_FAILED and oauth.access_token_expired():
        oauth.refresh_access_token()
    if integration.errors == ERROR_TOKEN_REFRESH_FAILED:
        raise CalendarSyncError(f"Token refresh failed for integration {integration.id}; reconnect the calendar")
    token = integration.access_token
    if not token:
        raise CalendarSyncError(f"Integration {integration.id} has no access token")
    return token


def _parse_when(when: dict | None) -> datetime | None:
    if not when:
        return None
    raw = when.get("dateTime") or when.get("date")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.get_default_timezone())
    return parsed


def _recurrence_instance_id(event: dict) -> str:
    if not event.get("recurringEventId"):
        return ""
    original = event.get("originalStartTime") or {}
    return (original.get("dateTime") or original.get("date") or "")[:64]


def _response_status(raw: str | None) -> str:
    mapping = {"needsAction": "needs_action", "accepted": "accepted", "declined": "declined", "tentative": "tentative"}
    return mapping.get(raw or "", "needs_action")


def _domain_of(email: str) -> str:
    _, address = parseaddr(email or "")
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""
