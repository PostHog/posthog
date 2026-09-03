from types import SimpleNamespace
from uuid import uuid4

import pytest
import unittest.mock

from posthog.models import User
from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities import (
    NotifyDAGMaterializationFailuresInputs,
    notify_dag_materialization_failures_activity,
)
from posthog.temporal.data_modeling.activities.notify_materialization_failure import _FailedView, _failure_copy

from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine, DataWarehouseSavedQuery
from products.notifications.backend.facade.api import TargetType

RUN_STARTED_AT = "2026-08-12T10:00:00+00:00"
# The shape a tier schedule produces, rather than an arbitrary long string.
PARENT_WORKFLOW_ID = f"execute-dag-{uuid4()}:86400-{RUN_STARTED_AT}"
SOURCE_ID_MAX_LENGTH = 64
RESOURCE_ID_MAX_LENGTH = 64
IDEMPOTENCY_KEY_MAX_LENGTH = 128


async def _saved_query(ateam, auser, name):
    return await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam, name=name, query={"query": "SELECT 1", "kind": "HogQLQuery"}, created_by=auser
    )


async def _failed_job(ateam, saved_query, *, run_started_at=RUN_STARTED_AT, parent=PARENT_WORKFLOW_ID, error="boom"):
    return await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
        saved_query=saved_query,
        status=DataModelingJob.Status.FAILED,
        engine=DataModelingJobEngine.CLICKHOUSE,
        error=error,
        parent_workflow_id=parent,
        workflow_id=f"materialize-view-dag-{saved_query.name}-{run_started_at}",
    )


def _access_allowing(allowed_by_view: dict[str, set[int]], *, raising_for: frozenset[int] = frozenset()):
    class FakeAccess:
        def __init__(self, user, team):
            self._user_id = user.id

        is_organization_admin = False

        def check_access_level_for_object(self, obj, required_level):
            if self._user_id in raising_for:
                raise RuntimeError("access check unavailable")
            return self._user_id in allowed_by_view.get(obj.name, set())

    return FakeAccess


def _inputs(ateam, adag, *, run_started_at=RUN_STARTED_AT):
    return NotifyDAGMaterializationFailuresInputs(
        team_id=ateam.pk,
        dag_id=str(adag.id),
        parent_workflow_id=PARENT_WORKFLOW_ID,
        run_started_at=run_started_at,
    )


@pytest.mark.asyncio
@pytest.mark.django_db
class TestNotifyDAGMaterializationFailures:
    async def test_one_notification_names_every_view_the_run_broke(
        self, activity_environment, ateam, adag, auser, aorganization
    ):
        member = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"member-{uuid4()}@posthog.com", None
        )
        names = ["alpha", "beta", "gamma"]
        for name in names:
            await _failed_job(ateam, await _saved_query(ateam, auser, name))

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.UserAccessControl",
                _access_allowing({name: {member.id} for name in names}),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
        ):
            sent = await activity_environment.run(notify_dag_materialization_failures_activity, _inputs(ateam, adag))

        assert sent == 1
        mock_create.assert_called_once()
        data = mock_create.call_args.args[0]
        assert data.title == "3 views failed to materialize"
        assert data.body == "alpha, beta, gamma"

    async def test_an_earlier_run_under_the_same_workflow_id_is_left_out(
        self, activity_environment, ateam, adag, auser, aorganization
    ):
        member = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"member-{uuid4()}@posthog.com", None
        )
        await _failed_job(
            ateam, await _saved_query(ateam, auser, "yesterday"), run_started_at="2026-08-11T10:00:00+00:00"
        )
        await _failed_job(ateam, await _saved_query(ateam, auser, "today"))

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.UserAccessControl",
                _access_allowing({"yesterday": {member.id}, "today": {member.id}}),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
        ):
            await activity_environment.run(notify_dag_materialization_failures_activity, _inputs(ateam, adag))

        data = mock_create.call_args.args[0]
        assert data.title == "today failed to materialize"

    async def test_a_view_already_failing_is_not_named_again(
        self, activity_environment, ateam, adag, auser, aorganization
    ):
        member = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"member-{uuid4()}@posthog.com", None
        )
        already_failing = await _saved_query(ateam, auser, "already_failing")
        await _failed_job(ateam, already_failing, run_started_at="2026-08-11T10:00:00+00:00")
        await _failed_job(ateam, already_failing)
        await _failed_job(ateam, await _saved_query(ateam, auser, "just_broke"))

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.UserAccessControl",
                _access_allowing({"already_failing": {member.id}, "just_broke": {member.id}}),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
        ):
            await activity_environment.run(notify_dag_materialization_failures_activity, _inputs(ateam, adag))

        data = mock_create.call_args.args[0]
        assert data.title == "just_broke failed to materialize"

    async def test_the_dedupe_key_fits_the_column_a_long_workflow_id_would_overflow(
        self, activity_environment, ateam, adag, auser, aorganization
    ):
        member = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"member-{uuid4()}@posthog.com", None
        )
        await _failed_job(ateam, await _saved_query(ateam, auser, "alpha"))

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.UserAccessControl",
                _access_allowing({"alpha": {member.id}}),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
        ):
            await activity_environment.run(notify_dag_materialization_failures_activity, _inputs(ateam, adag))

        data = mock_create.call_args.args[0]
        assert len(PARENT_WORKFLOW_ID) > SOURCE_ID_MAX_LENGTH, "the id under test has to be one that would overflow"
        assert len(data.source_id) <= SOURCE_ID_MAX_LENGTH
        assert len(data.resource_id) <= RESOURCE_ID_MAX_LENGTH
        assert len(data.idempotency_key) <= IDEMPOTENCY_KEY_MAX_LENGTH

    async def test_a_retry_asks_for_the_same_notification_rather_than_a_second_one(
        self, activity_environment, ateam, adag, auser, aorganization
    ):
        member = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"member-{uuid4()}@posthog.com", None
        )
        for name in ("alpha", "beta", "gamma"):
            await _failed_job(ateam, await _saved_query(ateam, auser, name))

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.UserAccessControl",
                _access_allowing({name: {member.id} for name in ("alpha", "beta", "gamma")}),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
        ):
            await activity_environment.run(notify_dag_materialization_failures_activity, _inputs(ateam, adag))
            await activity_environment.run(notify_dag_materialization_failures_activity, _inputs(ateam, adag))

        # Equal keys are what lets the unique constraint recognise the retry; the activity cannot
        # tell it is one, since a timeout can hand it the same work with nothing written yet.
        first, second = (call.args[0].idempotency_key for call in mock_create.call_args_list)
        assert first == second

    async def test_each_member_hears_once_about_everything_they_can_see(
        self, activity_environment, ateam, adag, auser, aorganization
    ):
        finance = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"finance-{uuid4()}@posthog.com", None
        )
        everyone_else = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"other-{uuid4()}@posthog.com", None
        )
        await _failed_job(ateam, await _saved_query(ateam, auser, "salaries"))
        await _failed_job(ateam, await _saved_query(ateam, auser, "pageviews"))

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.UserAccessControl",
                _access_allowing(
                    {"salaries": {finance.id}, "pageviews": {finance.id, everyone_else.id}},
                ),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
        ):
            sent = await activity_environment.run(notify_dag_materialization_failures_activity, _inputs(ateam, adag))

        assert sent == 2
        told: dict[int, str] = {}
        for call in mock_create.call_args_list:
            data = call.args[0]
            recipients = await database_sync_to_async(data.resolver.resolve)(TargetType.TEAM, str(ateam.pk), ateam.pk)
            for user_id in recipients:
                assert user_id not in told, "one run must not produce two notifications for one member"
                told[user_id] = f"{data.title} :: {data.body}"

        # The member allowed both hears about both, in one notification.
        assert told[finance.id].startswith("2 views failed to materialize")
        assert "salaries" in told[finance.id] and "pageviews" in told[finance.id]
        # The restricted view is never named to the member who cannot open it.
        assert told[everyone_else.id].startswith("pageviews failed to materialize")
        assert "salaries" not in told[everyone_else.id]

    async def test_a_member_whose_access_check_raises_is_not_told(
        self, activity_environment, ateam, adag, auser, aorganization
    ):
        allowed = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"allowed-{uuid4()}@posthog.com", None
        )
        unchecked = await database_sync_to_async(User.objects.create_and_join)(
            aorganization, f"unchecked-{uuid4()}@posthog.com", None
        )
        await _failed_job(ateam, await _saved_query(ateam, auser, "salaries"))

        with (
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.UserAccessControl",
                _access_allowing({"salaries": {allowed.id, unchecked.id}}, raising_for=frozenset({unchecked.id})),
            ),
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.capture_exception"
            ) as mock_capture,
            unittest.mock.patch(
                "posthog.temporal.data_modeling.activities.notify_materialization_failure.create_notification"
            ) as mock_create,
        ):
            sent = await activity_environment.run(notify_dag_materialization_failures_activity, _inputs(ateam, adag))

        assert sent == 1
        data = mock_create.call_args.args[0]
        recipients = await database_sync_to_async(data.resolver.resolve)(TargetType.TEAM, str(ateam.pk), ateam.pk)
        assert allowed.id in recipients, "a member the check cleared still hears about it"
        assert unchecked.id not in recipients, "a failed check must not admit the member it could not clear"
        assert mock_capture.called


class TestFailureCopy:
    @pytest.mark.parametrize(
        "names,expected_title,expected_body",
        [
            (["one"], "one failed to materialize", "it broke"),
            (["a", "b"], "2 views failed to materialize", "a, b"),
            (list("abcdefg"), "7 views failed to materialize", "a, b, c, d, e, and 2 more"),
        ],
    )
    def test_names_the_views_up_to_a_limit(self, names, expected_title, expected_body):
        views = [
            _FailedView(job=SimpleNamespace(error="it broke"), saved_query=SimpleNamespace(name=name))  # type: ignore[arg-type]
            for name in names
        ]

        assert _failure_copy(views) == (expected_title, expected_body)
