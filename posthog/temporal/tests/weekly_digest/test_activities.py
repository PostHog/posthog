import json
import inspect
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import fakeredis
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.messaging import MessagingRecord
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_notification_lock import OrganizationMemberNotificationLock
from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.team import Team
from posthog.models.user import User
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.temporal.weekly_digest.activities import (
    DIGEST_PAYLOAD_SIZE_LIMIT,
    NEW_ERROR_ISSUES_PER_TEAM_LIMIT,
    ActivityCancelled,
    UploadDeadlineExceeded,
    _cut_team_id_ranges,
    _query_team_usage_trends,
    _redis_url,
    _teams_in_range,
    _usage_trend_metric,
    generate_dashboard_lookup,
    generate_error_issue_lookup,
    generate_event_definition_lookup,
    generate_experiment_completed_lookup,
    generate_experiment_launched_lookup,
    generate_external_data_source_lookup,
    generate_feature_flag_lookup,
    generate_filter_lookup,
    generate_organization_digest_batch,
    generate_product_suggestion_lookup,
    generate_recording_lookup,
    generate_survey_lookup,
    generate_usage_trends_lookup,
    generate_user_notification_lookup,
    send_weekly_digest_batch,
)
from posthog.temporal.weekly_digest.keys import TeamDataKey, UserDataKey, org_digest_key, team_data_key, user_data_key
from posthog.temporal.weekly_digest.queries import query_team_ids_for_digest, query_teams_for_digest
from posthog.temporal.weekly_digest.types import (
    DEFAULT_PRODUCT_SUGGESTION_TEXT,
    CommonInput,
    Digest,
    GenerateDigestDataBatchInput,
    GenerateOrganizationDigestInput,
    SendWeeklyDigestBatchInput,
    TeamIdRange,
    UsageTrends,
)

from products.dashboards.backend.models.dashboard import Dashboard
from products.error_tracking.backend.facade.testing import create_issue
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.growth.backend.models import ProductPushCampaign
from products.surveys.backend.models import Survey
from products.warehouse_sources.backend.facade.models import ExternalDataSource

DJANGO_REDIS_URL = "redis://django-cache.example.com:6379"


def run_sync(activity_fn: Callable[..., Any], *args: Any) -> Any:
    # Activities are `@asyncify` wrappers around a sync body. Calling the body directly keeps the
    # test on the fast transactional database, which a thread-hopping coroutine could not see.
    return inspect.unwrap(activity_fn)(*args)


class FakeRedisServers:
    def __init__(self, common: CommonInput) -> None:
        self._servers = {
            _redis_url(common): fakeredis.FakeServer(),
            common.django_redis_url: fakeredis.FakeServer(),
        }
        self.digest = fakeredis.FakeRedis(server=self._servers[_redis_url(common)], decode_responses=True)
        self.django_cache = fakeredis.FakeRedis(server=self._servers[common.django_redis_url])

    def from_url(self, url: str, **kwargs: Any) -> fakeredis.FakeRedis:
        return fakeredis.FakeRedis(server=self._servers[url], decode_responses="decode_responses=true" in url)


@pytest.fixture
def common_input() -> CommonInput:
    return CommonInput(
        redis_ttl=3600 * 24 * 3,
        redis_host="digest-redis.example.com",
        redis_port=6379,
        batch_size=10,
        django_redis_url=DJANGO_REDIS_URL,
    )


@pytest.fixture
def redis_servers(common_input: CommonInput) -> Iterator[FakeRedisServers]:
    servers = FakeRedisServers(common_input)
    with patch("posthog.temporal.weekly_digest.activities.redis.Redis.from_url", side_effect=servers.from_url):
        yield servers


@pytest.fixture
def digest() -> Digest:
    # Rows created during the test carry `auto_now_add` timestamps, so the window ends after now.
    period_end = datetime.now(UTC) + timedelta(hours=1)
    return Digest(key="test-digest", period_start=period_end - timedelta(days=7), period_end=period_end)


@pytest.fixture(autouse=True)
def mock_heartbeater() -> Iterator[None]:
    # HeartbeaterSync reads the activity context, which the sync bodies do not have under test.
    with patch("posthog.temporal.weekly_digest.activities.HeartbeaterSync"):
        yield


def batch_input(team: Team, digest: Digest, common: CommonInput) -> GenerateDigestDataBatchInput:
    return GenerateDigestDataBatchInput(
        team_id_range=TeamIdRange(start=team.id, end=team.id + 1), digest=digest, common=common
    )


def create_user(organization: Organization, email: str, **fields: Any) -> User:
    return User.objects.create_and_join(organization, email, None, **fields)


@pytest.mark.django_db
def test_team_id_ranges_page_every_digest_team_exactly_once(organization, digest):
    for i in range(5):
        Team.objects.create(organization=organization, name=f"digest team {i}")
        if i == 2:
            # Sits inside a batch range, so a leak here shows up as an extra paged team.
            Team.objects.create(organization=organization, name="demo team", is_demo=True)

    common = CommonInput(batch_size=2, redis_host="localhost", redis_port=6379)
    expected = list(query_teams_for_digest().values_list("id", flat=True))

    paged: list[int] = []
    for team_id_range in _cut_team_id_ranges(list(query_team_ids_for_digest()), common.batch_size):
        team_ids = [
            team.id
            for team in _teams_in_range(
                GenerateDigestDataBatchInput(team_id_range=team_id_range, digest=digest, common=common)
            )
        ]
        assert len(team_ids) <= common.batch_size
        paged.extend(team_ids)

    assert paged == expected


def _make_dashboards(team: Team, other_team: Team, digest: Digest) -> list[str]:
    Dashboard.objects.create(team=team, name="New dashboard")
    Dashboard.objects.create(team=team, name="Generated Dashboard: onboarding")
    Dashboard.objects.create(team=other_team, name="Other team's dashboard")
    old = Dashboard.objects.create(team=team, name="Old dashboard")
    Dashboard.objects.filter(id=old.id).update(created_at=digest.period_start - timedelta(days=1))
    return ["New dashboard"]


def _make_event_definitions(team: Team, other_team: Team, digest: Digest) -> list[str]:
    EventDefinition.objects.create(team=team, name="new_event", created_at=timezone.now())
    EventDefinition.objects.create(team=other_team, name="other_event", created_at=timezone.now())
    EventDefinition.objects.create(team=team, name="old_event", created_at=digest.period_start - timedelta(days=1))
    return ["new_event"]


def _make_experiment(team: Team, name: str, **fields: Any) -> Experiment:
    flag = FeatureFlag.objects.create(
        team=team, key=f"flag-{uuid4().hex[:8]}", name=f"Feature Flag for Experiment {name}"
    )
    return Experiment.objects.create(team=team, feature_flag=flag, name=name, **fields)


def _make_experiments_launched(team: Team, other_team: Team, digest: Digest) -> list[str]:
    in_window = digest.period_end - timedelta(days=1)
    _make_experiment(team, "Launched", start_date=in_window)
    _make_experiment(team, "Launched and completed", start_date=in_window, end_date=in_window)
    _make_experiment(team, "Launched earlier", start_date=digest.period_start - timedelta(days=1))
    _make_experiment(other_team, "Other team's launch", start_date=in_window)
    return ["Launched"]


def _make_experiments_completed(team: Team, other_team: Team, digest: Digest) -> list[str]:
    in_window = digest.period_end - timedelta(days=1)
    _make_experiment(team, "Completed", start_date=digest.period_start - timedelta(days=30), end_date=in_window)
    _make_experiment(team, "Still running", start_date=in_window)
    _make_experiment(other_team, "Other team's completion", start_date=in_window, end_date=in_window)
    return ["Completed"]


def _make_external_data_source(team: Team, source_type: str, **fields: Any) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid4()),
        connection_id=str(uuid4()),
        status="Completed",
        source_type=source_type,
        **fields,
    )


def _make_external_data_sources(team: Team, other_team: Team, digest: Digest) -> list[str]:
    _make_external_data_source(team, "Stripe")
    _make_external_data_source(team, "Hubspot", deleted=True)
    _make_external_data_source(other_team, "Zendesk")
    old = _make_external_data_source(team, "Postgres")
    ExternalDataSource.objects.filter(id=old.id).update(created_at=digest.period_start - timedelta(days=1))
    return ["Stripe"]


def _make_feature_flags(team: Team, other_team: Team, digest: Digest) -> list[str]:
    FeatureFlag.objects.create(team=team, key="new-flag", name="New flag")
    FeatureFlag.objects.create(team=team, key="exp-flag", name="Feature Flag for Experiment checkout")
    FeatureFlag.objects.create(team=team, key="survey-flag", name="Targeting flag for survey NPS")
    FeatureFlag.objects.create(team=other_team, key="other-flag", name="Other team's flag")
    FeatureFlag.objects.create(
        team=team, key="old-flag", name="Old flag", created_at=digest.period_start - timedelta(days=1)
    )
    return ["New flag"]


def _make_survey(team: Team, name: str, **fields: Any) -> Survey:
    return Survey.objects.create(
        team=team, name=name, type="popover", questions=[{"type": "open", "id": "q1", "question": "Why?"}], **fields
    )


def _make_surveys(team: Team, other_team: Team, digest: Digest) -> list[str]:
    in_window = digest.period_end - timedelta(days=1)
    _make_survey(team, "Launched survey", start_date=in_window)
    _make_survey(team, "Draft survey")
    _make_survey(team, "Old survey", start_date=digest.period_start - timedelta(days=1))
    _make_survey(other_team, "Other team's survey", start_date=in_window)
    return ["Launched survey"]


def _make_error_issues(team: Team, other_team: Team, digest: Digest) -> list[str]:
    # One more than the cap, oldest first, so the cap must keep the newest ones.
    for index in range(NEW_ERROR_ISSUES_PER_TEAM_LIMIT + 1):
        create_issue(
            team_id=team.id, name=f"issue {index}", created_at=digest.period_start + timedelta(hours=index + 1)
        )
    create_issue(team_id=other_team.id, name="other team's issue", created_at=digest.period_end - timedelta(hours=1))
    create_issue(team_id=team.id, name="old issue", created_at=digest.period_start - timedelta(days=1))
    return [f"issue {index}" for index in range(1, NEW_ERROR_ISSUES_PER_TEAM_LIMIT + 1)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "activity_fn,key_kind,payload_field,make_rows",
    [
        (generate_dashboard_lookup, TeamDataKey.DASHBOARDS, "name", _make_dashboards),
        (generate_event_definition_lookup, TeamDataKey.EVENT_DEFINITIONS, "name", _make_event_definitions),
        (generate_experiment_launched_lookup, TeamDataKey.EXPERIMENTS_LAUNCHED, "name", _make_experiments_launched),
        (generate_experiment_completed_lookup, TeamDataKey.EXPERIMENTS_COMPLETED, "name", _make_experiments_completed),
        (
            generate_external_data_source_lookup,
            TeamDataKey.EXTERNAL_DATA_SOURCES,
            "source_type",
            _make_external_data_sources,
        ),
        (generate_feature_flag_lookup, TeamDataKey.FEATURE_FLAGS, "name", _make_feature_flags),
        (generate_survey_lookup, TeamDataKey.SURVEYS_LAUNCHED, "name", _make_surveys),
        (generate_error_issue_lookup, TeamDataKey.ERROR_ISSUES, "name", _make_error_issues),
    ],
)
def test_generic_lookup_stores_only_this_teams_rows_from_the_window(
    activity_fn, key_kind, payload_field, make_rows, organization, team, redis_servers, common_input, digest
):
    quiet_team = _make_team(organization, "quiet team")
    other_team = _make_team(organization, "other team")
    expected = make_rows(team, other_team, digest)
    # Left over from an earlier attempt of the same digest; the quiet team has no rows anymore.
    redis_servers.digest.set(team_data_key(digest.key, key_kind, quiet_team.id), "[]")

    run_sync(
        activity_fn,
        GenerateDigestDataBatchInput(
            team_id_range=TeamIdRange(start=team.id, end=other_team.id), digest=digest, common=common_input
        ),
    )

    key = team_data_key(digest.key, key_kind, team.id)
    stored = json.loads(redis_servers.digest.get(key))
    assert sorted(row[payload_field] for row in stored) == sorted(expected)
    assert 0 < redis_servers.digest.ttl(key) <= common_input.redis_ttl
    # The quiet team is in range with nothing new, so its stale key goes; the other team is out of range.
    assert team.id < quiet_team.id < other_team.id
    assert redis_servers.digest.keys(f"{digest.key}-{key_kind}-*") == [key]


def _run_lookup(activity_fn: Callable[..., Any]) -> Callable[[TeamIdRange, Digest, CommonInput], None]:
    return lambda team_range, digest, common: run_sync(
        activity_fn, GenerateDigestDataBatchInput(team_id_range=team_range, digest=digest, common=common)
    )


def _run_organization_digest_batch(team_range: TeamIdRange, digest: Digest, common: CommonInput) -> None:
    run_sync(
        generate_organization_digest_batch,
        GenerateOrganizationDigestInput(batch=(0, Organization.objects.count()), digest=digest, common=common),
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "run_activity,make_row",
    [
        (_run_lookup(generate_dashboard_lookup), lambda team: Dashboard.objects.create(team=team, name="Dashboard")),
        (_run_lookup(generate_error_issue_lookup), lambda team: create_issue(team_id=team.id, name="issue")),
        (
            _run_lookup(generate_filter_lookup),
            lambda team: SessionRecordingPlaylist.objects.create(team=team, name="Filter", type="filters"),
        ),
        (_run_organization_digest_batch, lambda team: None),
    ],
)
def test_batch_activities_run_a_fixed_number_of_queries_per_range(
    run_activity, make_row, organization, team, redis_servers, common_input, digest
):
    # Each activity runs a fixed set of range-wide queries, so adding teams to the range adds no queries.
    def queries_for(team_count: int) -> int:
        teams = [team, *(_make_team(organization, f"team {index}") for index in range(team_count - 1))]
        for extra_team in teams:
            make_row(extra_team)
        team_range = TeamIdRange(start=team.id, end=max(extra_team.id for extra_team in teams) + 1)
        with CaptureQueriesContext(connection) as queries:
            run_activity(team_range, digest, common_input)
        return len(queries)

    assert queries_for(1) == queries_for(4)


@pytest.mark.django_db
def test_generate_filter_lookup_orders_filters_by_cached_recording_count(team, redis_servers, common_input, digest):
    quiet = SessionRecordingPlaylist.objects.create(team=team, name="Quiet filter", type="filters")
    busy = SessionRecordingPlaylist.objects.create(team=team, name="Busy filter", type="filters")
    SessionRecordingPlaylist.objects.create(team=team, name="A collection", type="collection")
    SessionRecordingPlaylist.objects.create(team=team, name="Deleted filter", type="filters", deleted=True)
    SessionRecordingPlaylist.objects.create(team=team, name="", derived_name="(Untitled)", type="filters")
    redis_servers.django_cache.set(
        f"{PLAYLIST_COUNT_REDIS_PREFIX}{busy.short_id}",
        json.dumps(
            {
                "session_ids": ["s1", "s2", "s3"],
                "has_more": True,
                "previous_ids": None,
                "refreshed_at": timezone.now().isoformat(),
                "error_count": 0,
                "errored_at": None,
            }
        ),
    )
    redis_servers.django_cache.set(f"{PLAYLIST_COUNT_REDIS_PREFIX}{quiet.short_id}", "not json")

    run_sync(generate_filter_lookup, batch_input(team, digest, common_input))

    stored = json.loads(redis_servers.digest.get(team_data_key(digest.key, TeamDataKey.SAVED_FILTERS, team.id)))
    assert [(f["name"], f["recording_count"], f["more_available"]) for f in stored] == [
        ("Busy filter", 3, True),
        ("Quiet filter", 0, False),
    ]


@pytest.mark.django_db
def test_generate_recording_lookup_counts_expiring_sessions_per_team(
    organization, team, redis_servers, common_input, digest
):
    other_team = _make_team(organization, "other team")
    quiet_team = _make_team(organization, "quiet team")
    now = datetime.now(UTC)
    # 30-day retention: sessions started 25 days ago expire in 5 days, inside the 10-day threshold.
    for session_id in ("expiring-1", "expiring-2"):
        produce_replay_summary(
            team_id=team.id,
            session_id=session_id,
            first_timestamp=now - timedelta(days=25),
            last_timestamp=now - timedelta(days=25),
            retention_period_days=30,
            ensure_analytics_event_in_session=False,
        )
    # Started 5 days ago, so it has 25 days left and is not about to expire.
    produce_replay_summary(
        team_id=team.id,
        session_id="fresh",
        first_timestamp=now - timedelta(days=5),
        last_timestamp=now - timedelta(days=5),
        retention_period_days=30,
        ensure_analytics_event_in_session=False,
    )
    # Left over from an earlier attempt of the same digest; the quiet team has no sessions.
    redis_servers.digest.set(
        team_data_key(digest.key, TeamDataKey.EXPIRING_RECORDINGS, quiet_team.id), json.dumps({"recording_count": 9})
    )
    produce_replay_summary(
        team_id=other_team.id,
        session_id="other-expiring",
        first_timestamp=now - timedelta(days=25),
        last_timestamp=now - timedelta(days=25),
        retention_period_days=30,
        ensure_analytics_event_in_session=False,
    )

    run_sync(
        generate_recording_lookup,
        GenerateDigestDataBatchInput(
            team_id_range=TeamIdRange(start=team.id, end=quiet_team.id + 1), digest=digest, common=common_input
        ),
    )

    def stored_count(for_team: Team) -> dict | None:
        raw = redis_servers.digest.get(team_data_key(digest.key, TeamDataKey.EXPIRING_RECORDINGS, for_team.id))
        return json.loads(raw) if raw else None

    assert stored_count(team) == {"recording_count": 2}
    assert stored_count(other_team) == {"recording_count": 1}
    assert stored_count(quiet_team) is None


def _make_team(organization: Organization, name: str) -> Team:
    return Team.objects.create(organization=organization, name=name)


@pytest.mark.django_db
def test_generate_user_notification_lookup_respects_settings_and_organization_locks(
    organization, team, redis_servers, common_input, digest
):
    muted_team = _make_team(organization, "muted for one user")
    everyone = create_user(organization, "everyone@example.com")
    muted_one = create_user(
        organization,
        "muted-one@example.com",
        partial_notification_settings={"project_weekly_digest_disabled": {str(muted_team.id): True}},
    )
    muted_all = create_user(
        organization, "muted-all@example.com", partial_notification_settings={"all_weekly_digest_disabled": True}
    )
    locked = create_user(organization, "locked@example.com")
    OrganizationMemberNotificationLock.objects.create(
        organization=organization,
        organization_membership=OrganizationMembership.objects.get(user=locked, organization=organization),
        setting="project_weekly_digest_disabled",
        scope_id=str(team.id),
        locked_value=True,
    )
    create_user(organization, "inactive@example.com", is_active=False)

    run_sync(
        generate_user_notification_lookup,
        GenerateDigestDataBatchInput(
            team_id_range=TeamIdRange(start=team.id, end=muted_team.id + 1), digest=digest, common=common_input
        ),
    )

    def notify_teams(user: User) -> set[int]:
        key = user_data_key(digest.key, UserDataKey.NOTIFY_TEAMS, user.id)
        return {int(team_id) for team_id in redis_servers.digest.smembers(key)}

    assert notify_teams(everyone) == {team.id, muted_team.id}
    assert notify_teams(muted_one) == {team.id}
    assert notify_teams(muted_all) == set()
    assert notify_teams(locked) == {muted_team.id}
    assert set(redis_servers.digest.keys(f"{digest.key}-{UserDataKey.NOTIFY_TEAMS}-*")) == {
        user_data_key(digest.key, UserDataKey.NOTIFY_TEAMS, user.id) for user in [everyone, muted_one, locked]
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_generate_user_notification_lookup_activity_runs_the_settings_check_off_the_event_loop(
    activity_environment, organization, team, redis_servers, common_input, digest
):
    # The activity runs on the event loop the way the worker calls it. `should_send_notification`
    # queries Postgres, which Django refuses from a coroutine, so a body that stays on the loop
    # skips every team and writes no notification set at all.
    user = await sync_to_async(create_user)(organization, "member@example.com")

    await activity_environment.run(generate_user_notification_lookup, batch_input(team, digest, common_input))

    assert redis_servers.digest.smembers(user_data_key(digest.key, UserDataKey.NOTIFY_TEAMS, user.id)) == {str(team.id)}


@pytest.mark.django_db
@pytest.mark.parametrize("project_already_uses_product", [False, True])
def test_generate_product_suggestion_lookup_targets_opted_in_users_of_projects_without_the_product(
    project_already_uses_product, organization, team, redis_servers, common_input, digest
):
    ProductPushCampaign.objects.create(
        organization=organization,
        product_key="session_replay",
        status=ProductPushCampaign.Status.ACTIVE,
        started_at=timezone.now() - timedelta(days=1),
        reason_text="Give replay a go",
    )
    opted_in = create_user(organization, "opted-in@example.com")
    create_user(organization, "opted-out@example.com", allow_sidebar_suggestions=False)
    if project_already_uses_product:
        ProductIntent.objects.create(team=team, product_type="session_replay", activated_at=timezone.now())

    run_sync(generate_product_suggestion_lookup, batch_input(team, digest, common_input))

    suggestion_keys = redis_servers.digest.keys(f"{digest.key}-{UserDataKey.PRODUCT_SUGGESTION}-*")
    if project_already_uses_product:
        assert suggestion_keys == []
        return

    assert suggestion_keys == [user_data_key(digest.key, UserDataKey.PRODUCT_SUGGESTION, opted_in.id)]
    stored = json.loads(redis_servers.digest.get(suggestion_keys[0]))
    assert stored == {"team_id": team.id, "product_path": "Session replay", "reason_text": "Give replay a go"}


@pytest.mark.django_db
def test_generate_organization_digest_batch_defaults_missing_team_data(
    organization, team, redis_servers, common_input, digest
):
    silent_team = _make_team(organization, "silent team")
    Team.objects.create(organization=organization, name="demo team", is_demo=True)
    broken_organization = Organization.objects.create(name="broken org")
    broken_team = _make_team(broken_organization, "broken team")
    redis_servers.digest.set(team_data_key(digest.key, TeamDataKey.DASHBOARDS, broken_team.id), "not json")
    redis_servers.digest.set(
        team_data_key(digest.key, TeamDataKey.DASHBOARDS, team.id), json.dumps([{"name": "Dashboard", "id": 1}])
    )
    redis_servers.digest.set(
        team_data_key(digest.key, TeamDataKey.EXPIRING_RECORDINGS, team.id), json.dumps({"recording_count": 7})
    )
    run_sync(
        generate_organization_digest_batch,
        GenerateOrganizationDigestInput(batch=(0, Organization.objects.count()), digest=digest, common=common_input),
    )

    # One organization's malformed value skips that organization only.
    assert redis_servers.digest.get(org_digest_key(digest.key, broken_organization.id)) is None
    stored = json.loads(redis_servers.digest.get(org_digest_key(digest.key, organization.id)))
    assert stored["name"] == organization.name
    assert [td["id"] for td in stored["team_digests"]] == sorted([team.id, silent_team.id])
    by_team = {td["id"]: td for td in stored["team_digests"]}
    assert by_team[team.id]["dashboards"] == [{"name": "Dashboard", "id": 1}]
    assert by_team[team.id]["expiring_recordings"] == {"recording_count": 7}
    assert by_team[silent_team.id]["dashboards"] == []
    assert by_team[silent_team.id]["expiring_recordings"] == {"recording_count": 0}
    assert by_team[silent_team.id]["usage_trends"] == {"metrics": []}


def _org_digest_json(organization: Organization, team: Team) -> str:
    return json.dumps(
        {
            "id": str(organization.id),
            "name": organization.name,
            "created_at": "2024-01-01T00:00:00Z",
            "team_digests": [
                {
                    "id": team.id,
                    "name": team.name,
                    "dashboards": [{"name": "Test Dashboard", "id": 1}],
                    "event_definitions": [],
                    "experiments_launched": [
                        {"name": "Experiment A", "id": 1, "start_date": "2024-01-01T00:00:00Z"},
                        {"name": "Experiment B", "id": 2, "start_date": "2024-01-01T00:00:00Z"},
                    ],
                    "experiments_completed": [],
                    "external_data_sources": [{"source_type": "stripe", "id": str(uuid4())}],
                    "feature_flags": [],
                    "filters": [],
                    "expiring_recordings": {"recording_count": 0},
                    "surveys_launched": [],
                }
            ],
        }
    )


def _send_input(
    organization: Organization, digest: Digest, common: CommonInput, dry_run: bool
) -> SendWeeklyDigestBatchInput:
    organization_index = list(Organization.objects.order_by("id").values_list("id", flat=True)).index(organization.id)
    return SendWeeklyDigestBatchInput(
        batch=(organization_index, organization_index + 1),
        dry_run=dry_run,
        allow_already_sent=False,
        digest=digest,
        common=common,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "dry_run,already_sent,expected_captures",
    [
        (False, False, 1),
        (True, False, 0),
        (False, True, 0),
    ],
)
def test_send_weekly_digest_batch_emails_subscribed_members_once(
    dry_run, already_sent, expected_captures, organization, team, redis_servers, common_input, digest
):
    subscribed = create_user(organization, "subscribed@example.com")
    create_user(organization, "unsubscribed@example.com")
    redis_servers.digest.set(org_digest_key(digest.key, organization.id), _org_digest_json(organization, team))
    redis_servers.digest.sadd(user_data_key(digest.key, UserDataKey.NOTIFY_TEAMS, subscribed.id), team.id)
    redis_servers.digest.set(
        user_data_key(digest.key, UserDataKey.PRODUCT_SUGGESTION, subscribed.id),
        json.dumps({"team_id": team.id, "product_path": "Error tracking", "reason_text": None}),
    )
    if already_sent:
        record, _ = MessagingRecord.objects.get_or_create(raw_email=f"org_{organization.id}", campaign_key=digest.key)
        record.sent_at = timezone.now()
        record.save()
    ph_client = MagicMock()

    with patch("posthog.temporal.weekly_digest.activities.get_ph_client", return_value=ph_client):
        run_sync(send_weekly_digest_batch, _send_input(organization, digest, common_input, dry_run=dry_run))

    assert ph_client.capture.call_count == expected_captures
    assert ph_client.shutdown.called
    record = MessagingRecord.objects.get(campaign_key=digest.key)
    # A dry run must not stamp the record, or the real run that follows would skip the organization.
    assert (record.sent_at is not None) is (not dry_run)
    if expected_captures == 0:
        return

    method_names = [name for name, _, _ in ph_client.method_calls]
    assert method_names.index("capture") < method_names.index("flush")

    capture = ph_client.capture.call_args.kwargs
    assert capture["distinct_id"] == subscribed.distinct_id
    assert capture["event"] == "transactional email"
    assert capture["groups"]["organization"] == str(organization.id)
    (team_payload,) = capture["properties"]["teams"]
    assert team_payload["team_id"] == team.id
    assert team_payload["report"]["new_product_suggestion"] == {
        "product_path": "Error tracking",
        "reason_text": DEFAULT_PRODUCT_SUGGESTION_TEXT,
    }


@activity.defn(name="send-weekly-digest-batch-body", no_thread_cancel_exception=True)
def send_weekly_digest_batch_body(input: SendWeeklyDigestBatchInput) -> None:
    # Runs the sync body under a test activity context. Without the thread cancel exception, cancelling
    # only sets the cancellation event, which is all a worker thread behind `@asyncify` receives.
    inspect.unwrap(send_weekly_digest_batch)(input)


@pytest.mark.django_db
def test_send_weekly_digest_batch_stops_sending_once_the_activity_is_cancelled(
    activity_environment, organization, team, redis_servers, common_input, digest
):
    members = [create_user(organization, f"member-{index}@example.com") for index in range(3)]
    redis_servers.digest.set(org_digest_key(digest.key, organization.id), _org_digest_json(organization, team))
    for member in members:
        redis_servers.digest.sadd(user_data_key(digest.key, UserDataKey.NOTIFY_TEAMS, member.id), team.id)
    ph_client = MagicMock()
    ph_client.capture.side_effect = lambda **_: activity_environment.cancel()

    with (
        patch("posthog.temporal.weekly_digest.activities.get_ph_client", return_value=ph_client),
        pytest.raises(ActivityCancelled),
    ):
        activity_environment.run(
            send_weekly_digest_batch_body, _send_input(organization, digest, common_input, dry_run=False)
        )

    assert ph_client.capture.call_count == 1
    # A queued event is unconfirmed until a drain finishes, so the cancelled attempt leaves the record unsent.
    assert MessagingRecord.objects.get(campaign_key=digest.key).sent_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "drop,expected_captures",
    [
        ("failed_upload", 1),
        ("queue_full", 1),
        ("oversized", 0),
    ],
)
def test_send_weekly_digest_batch_leaves_organization_unsent_when_an_event_is_dropped(
    drop, expected_captures, organization, team, redis_servers, common_input, digest
):
    subscribed = create_user(organization, "subscribed@example.com")
    redis_servers.digest.set(org_digest_key(digest.key, organization.id), _org_digest_json(organization, team))
    redis_servers.digest.sadd(user_data_key(digest.key, UserDataKey.NOTIFY_TEAMS, subscribed.id), team.id)
    ph_client = MagicMock()

    def make_client(**kwargs: Any) -> MagicMock:
        if drop == "failed_upload":
            # The SDK reports a failed upload through on_error while flush drains the queue.
            def flush(**_: Any) -> None:
                kwargs["on_error"](
                    RuntimeError("upload failed"), [{"properties": {"organization_id": str(organization.id)}}]
                )

            ph_client.flush.side_effect = flush
        elif drop == "queue_full":
            ph_client.capture.return_value = None
        return ph_client

    with (
        patch("posthog.temporal.weekly_digest.activities.get_ph_client", side_effect=make_client),
        patch(
            "posthog.temporal.weekly_digest.activities.DIGEST_PAYLOAD_SIZE_LIMIT",
            100 if drop == "oversized" else DIGEST_PAYLOAD_SIZE_LIMIT,
        ),
    ):
        run_sync(send_weekly_digest_batch, _send_input(organization, digest, common_input, dry_run=False))

    assert ph_client.capture.call_count == expected_captures
    assert ph_client.shutdown.called
    record = MessagingRecord.objects.get(campaign_key=digest.key)
    assert record.sent_at is None


@pytest.mark.django_db
def test_send_weekly_digest_batch_leaves_organization_unsent_when_the_attempt_runs_out_of_time(
    activity_environment, organization, team, redis_servers, common_input, digest
):
    subscribed = create_user(organization, "subscribed@example.com")
    redis_servers.digest.set(org_digest_key(digest.key, organization.id), _org_digest_json(organization, team))
    redis_servers.digest.sadd(user_data_key(digest.key, UserDataKey.NOTIFY_TEAMS, subscribed.id), team.id)
    ph_client = MagicMock()
    activity_environment.info = dataclasses.replace(
        activity_environment.info,
        started_time=datetime.now(UTC) - timedelta(minutes=30),
        start_to_close_timeout=timedelta(minutes=30),
    )

    with (
        patch("posthog.temporal.weekly_digest.activities.get_ph_client", return_value=ph_client),
        pytest.raises(UploadDeadlineExceeded),
    ):
        activity_environment.run(
            send_weekly_digest_batch_body, _send_input(organization, digest, common_input, dry_run=False)
        )

    assert ph_client.capture.call_count == 1
    assert ph_client.shutdown.called
    assert MessagingRecord.objects.get(campaign_key=digest.key).sent_at is None


@pytest.mark.parametrize(
    "current,previous,expected_direction,expected_change_pct,expected_has_baseline",
    [
        (150, 100, "up", 50, True),
        (50, 100, "down", 50, True),
        (100, 100, "flat", 0, True),
        # No previous-week baseline: growth from 0 must not be reported as "no change"
        (10_000, 0, "flat", 0, False),
        (0, 0, "flat", 0, False),
    ],
)
def test_usage_trend_metric(current, previous, expected_direction, expected_change_pct, expected_has_baseline):
    metric = _usage_trend_metric("Events", current, previous)

    assert metric.current == current
    assert metric.previous == previous
    assert metric.direction == expected_direction
    assert metric.change_pct == expected_change_pct
    assert metric.has_baseline is expected_has_baseline


@pytest.mark.django_db
def test_query_team_usage_trends_windows_persons_and_test_accounts(team):
    # Guards the previously-unvalidated usage query: window boundaries, distinct-person
    # "active users" (matching DAU/WAU), and that filterTestAccounts drops test traffic.
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    period_start = period_end - timedelta(days=7)  # current window [period_start, period_end)

    p1, p2 = str(uuid4()), str(uuid4())
    # Current window: 3 events across 2 distinct persons.
    _create_event(team=team, event="$pageview", distinct_id="a", person_id=p1, timestamp="2024-01-03T00:00:00Z")
    _create_event(team=team, event="$pageview", distinct_id="a", person_id=p1, timestamp="2024-01-04T00:00:00Z")
    _create_event(team=team, event="$pageview", distinct_id="b", person_id=p2, timestamp="2024-01-05T00:00:00Z")
    # Previous window: 1 event, 1 person.
    _create_event(team=team, event="$pageview", distinct_id="a", person_id=p1, timestamp="2023-12-31T00:00:00Z")
    # Exactly at period_end is excluded (window is half-open: timestamp < cur_end).
    _create_event(team=team, event="$pageview", distinct_id="b", person_id=p2, timestamp="2024-01-08T00:00:00Z")

    # test_account_filters are phrased to KEEP real accounts, so "is_not localhost" drops the test event below.
    team.test_account_filters = [{"key": "$host", "type": "event", "value": "localhost", "operator": "is_not"}]
    team.save()
    # Test-account traffic in the current window must not inflate the numbers.
    _create_event(
        team=team,
        event="$pageview",
        distinct_id="t",
        person_id=str(uuid4()),
        timestamp="2024-01-06T00:00:00Z",
        properties={"$host": "localhost"},
    )
    flush_persons_and_events()

    result = _query_team_usage_trends(team, period_start, period_end)

    assert result is not None
    events, users = result.metrics
    assert (events.label, events.current, events.previous) == ("Events", 3, 1)
    assert (users.label, users.current, users.previous) == ("Active users", 2, 1)


@pytest.mark.django_db
def test_generate_usage_trends_lookup_queries_only_teams_with_events(
    organization, team, redis_servers, common_input, digest
):
    idle_team = _make_team(organization, "idle team")
    _create_event(team=team, event="$pageview", distinct_id="a", timestamp=digest.period_end - timedelta(days=1))
    _create_event(team=idle_team, event="$pageview", distinct_id="b", timestamp=digest.period_start - timedelta(days=1))
    flush_persons_and_events()
    # Left over from an earlier attempt of the same digest; the idle team has no events this week.
    redis_servers.digest.set(team_data_key(digest.key, TeamDataKey.USAGE_TRENDS, idle_team.id), '{"metrics": []}')

    with patch(
        "posthog.temporal.weekly_digest.activities._query_team_usage_trends", wraps=_query_team_usage_trends
    ) as query_team_usage_trends:
        run_sync(
            generate_usage_trends_lookup,
            GenerateDigestDataBatchInput(
                team_id_range=TeamIdRange(start=team.id, end=idle_team.id + 1), digest=digest, common=common_input
            ),
        )

    assert [call.args[0].id for call in query_team_usage_trends.call_args_list] == [team.id]
    stored = json.loads(redis_servers.digest.get(team_data_key(digest.key, TeamDataKey.USAGE_TRENDS, team.id)))
    assert [(metric["label"], metric["current"]) for metric in stored["metrics"]] == [
        ("Events", 1),
        ("Active users", 1),
    ]
    assert redis_servers.digest.get(team_data_key(digest.key, TeamDataKey.USAGE_TRENDS, idle_team.id)) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "side_effects,should_raise",
    [
        # Systemic failure (broken query / offline outage): every team errors -> fail the run loudly.
        ([Exception("boom"), Exception("boom")], True),
        # Isolated failure: one team errors, another succeeds -> tolerate and keep going.
        ([Exception("boom"), UsageTrends(metrics=[])], False),
    ],
)
def test_generate_usage_trends_lookup_raises_only_when_every_team_fails(
    side_effects, should_raise, organization, team, redis_servers, common_input, digest
):
    second_team = _make_team(organization, "second team")
    input_data = GenerateDigestDataBatchInput(
        team_id_range=TeamIdRange(start=team.id, end=second_team.id + 1), digest=digest, common=common_input
    )

    with (
        patch("posthog.temporal.weekly_digest.activities._active_team_ids", return_value={team.id, second_team.id}),
        patch("posthog.temporal.weekly_digest.activities._query_team_usage_trends", side_effect=side_effects),
    ):
        if should_raise:
            with pytest.raises(RuntimeError):
                run_sync(generate_usage_trends_lookup, input_data)
        else:
            run_sync(generate_usage_trends_lookup, input_data)
            assert (
                redis_servers.digest.get(team_data_key(digest.key, TeamDataKey.USAGE_TRENDS, second_team.id))
                is not None
            )
