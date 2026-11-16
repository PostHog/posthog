import uuid
from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest

from django.apps import apps
from django.db import models
from django.db.models.signals import pre_delete
from django.utils import timezone

from parameterized import parameterized

from posthog.integrations import IntegrationManager, lifecycle
from posthog.models import Team, User
from posthog.models.integration import Integration

# The fields of a row that points at an integration, without the foreign key itself.
Fields = Callable[[Team, User], dict[str, Any]]


def _create(label: str, **fields: Any) -> models.Model:
    return apps.get_model(label)._base_manager.create(**fields)


def _choice(label: str, field: str) -> str:
    return apps.get_model(label)._meta.get_field(field).choices[0][0]


def _task(team: Team) -> models.Model:
    return _create(
        "tasks.Task", team=team, title="t", description="d", origin_product=_choice("tasks.Task", "origin_product")
    )


def _slack_thread_task_mapping(team: Team, user: User) -> dict[str, Any]:
    task = _task(team)
    return {
        "team": team,
        "slack_workspace_id": "T1",
        "channel": "C1",
        "thread_ts": "1.0",
        "task": task,
        "task_run": _create("tasks.TaskRun", team=team, task=task),
        "mentioning_slack_user_id": "U1",
    }


def _report(team: Team) -> models.Model:
    return _create("signals.SignalReport", team=team)


# (model label, foreign key field) -> (the `on_delete` rule of the field, the other fields of a row).
FOREIGN_KEYS: dict[tuple[str, str], tuple[Any, Fields]] = {
    ("posthog.SessionRecordingExternalReference", "integration"): (
        models.CASCADE,
        lambda team, user: {
            "session_recording": _create("posthog.SessionRecording", team=team, session_id=str(uuid.uuid4()))
        },
    ),
    ("posthog.CommentSlackThread", "integration"): (
        models.CASCADE,
        lambda team, user: {
            "team": team,
            "scope": "Insight",
            "source_comment": _create("posthog.Comment", team=team, scope="Insight"),
            "slack_channel_id": "C1",
        },
    ),
    ("posthog.IntegrationRepositoryCacheEntry", "integration"): (
        models.CASCADE,
        lambda team, user: {
            "team": team,
            "full_name": "posthog/posthog",
            "default_branch": "main",
            "default_branch_sha": "abc",
        },
    ),
    ("tasks.Channel", "github_integration"): (models.SET_NULL, lambda team, user: {"team": team, "name": "space"}),
    ("tasks.Task", "github_integration"): (
        models.SET_NULL,
        lambda team, user: {
            "team": team,
            "title": "t",
            "description": "d",
            "origin_product": _choice("tasks.Task", "origin_product"),
        },
    ),
    ("tasks.SandboxSnapshot", "integration"): (models.SET_NULL, lambda team, user: {"external_id": "snap"}),
    ("error_tracking.ErrorTrackingExternalReference", "integration"): (
        models.CASCADE,
        lambda team, user: {"issue": _create("error_tracking.ErrorTrackingIssue", team=team)},
    ),
    ("error_tracking.ErrorTrackingAlertDestination", "integration"): (
        models.SET_NULL,
        lambda team, user: {
            "team": team,
            "alert": _create("error_tracking.ErrorTrackingAlert", team=team, name="alert"),
            "channel_type": "slack",
        },
    ),
    ("data_modeling.GitHubSyncConfig", "integration"): (models.SET_NULL, lambda team, user: {"team": team}),
    ("customer_analytics.EventStream", "slack_integration"): (
        models.SET_NULL,
        lambda team, user: {"team": team, "created_by": user},
    ),
    ("customer_analytics.FeatureRequestGitHubLink", "integration"): (
        models.SET_NULL,
        lambda team, user: {
            "team": team,
            "feature_request": _create("customer_analytics.FeatureRequest", team=team, title="f"),
            "installation_id": "1",
            "repository": "posthog/posthog",
            "issue_number": 1,
        },
    ),
    ("slack_app.SlackThreadTaskMapping", "integration"): (models.CASCADE, _slack_thread_task_mapping),
    ("slack_app.SlackUserProfileCache", "integration"): (models.CASCADE, lambda team, user: {"slack_user_id": "U1"}),
    ("slack_app.SlackSettings", "default_integration"): (
        models.CASCADE,
        lambda team, user: {"slack_workspace_id": "T1"},
    ),
    ("signals.SignalTeamConfig", "issue_tracking_integration"): (models.SET_NULL, lambda team, user: {"team": team}),
    ("signals.SignalUserAutonomyConfig", "slack_notification_integration"): (
        models.SET_NULL,
        lambda team, user: {"user": user},
    ),
    ("signals.SignalReportTrackerIssue", "integration"): (
        models.SET_NULL,
        lambda team, user: {
            "team": team,
            "report": _report(team),
            "status": _choice("signals.SignalReportTrackerIssue", "status"),
        },
    ),
    ("signals.SignalReportSlackThread", "integration"): (
        models.SET_NULL,
        lambda team, user: {
            "team": team,
            "report": _report(team),
            "slack_workspace_id": "T1",
            "channel": "C1",
            "thread_ts": "1.0",
        },
    ),
    ("messaging.OptOutSyncConfig", "app_integration"): (models.SET_NULL, lambda team, user: {"team": team}),
    ("messaging.OptOutSyncConfig", "webhook_integration"): (models.SET_NULL, lambda team, user: {"team": team}),
    ("messaging.OptOutSyncConfig", "track_integration"): (models.SET_NULL, lambda team, user: {"team": team}),
    ("messaging.ProviderImportRun", "integration"): (
        models.SET_NULL,
        lambda team, user: {"team": team, "provider": _choice("messaging.ProviderImportRun", "provider")},
    ),
    ("warehouse_sources.ExternalDataDestination", "integration"): (
        models.SET_NULL,
        lambda team, user: {
            "team": team,
            "type": _choice("warehouse_sources.ExternalDataDestination", "type"),
            "name": "destination",
        },
    ),
    ("batch_exports.BatchExportDestination", "integration"): (models.SET_NULL, lambda team, user: {"type": "S3"}),
    ("subscriptions.Subscription", "integration"): (
        models.SET_NULL,
        lambda team, user: {
            "team": team,
            "target_type": "slack",
            "target_value": "C1",
            "frequency": "daily",
            "start_date": timezone.now(),
        },
    ),
}


class TestForeignKeyHooks(BaseTest):
    def test_every_foreign_key_to_integration_has_a_case(self) -> None:
        foreign_keys = {
            (model._meta.label, field.name): field.remote_field.on_delete
            for model in apps.get_models()
            for field in model._meta.concrete_fields
            if field.is_relation and field.related_model is Integration and field.remote_field is not None
        }

        assert foreign_keys == {key: on_delete for key, (on_delete, _fields) in FOREIGN_KEYS.items()}

    @parameterized.expand(
        [
            (f"{label}.{field}", label, field, on_delete, fields)
            for (label, field), (on_delete, fields) in FOREIGN_KEYS.items()
        ]
    )
    def test_the_sdk_delete_does_the_work_of_the_foreign_key(
        self, _name: str, label: str, field_name: str, on_delete: Any, fields: Fields
    ) -> None:
        model = apps.get_model(label)
        column = model._meta.get_field(field_name).attname
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="fk-hook")
        dependent = model._base_manager.create(**fields(self.team, self.user), **{field_name: integration})
        at_delete: list[list[int | None]] = []

        def values() -> list[int | None]:
            return list(model._base_manager.filter(pk=dependent.pk).values_list(column, flat=True))

        # Django deletes and nulls the dependent rows after `pre_delete`, so the values here show the work of the
        # hooks alone. The foreign keys still do the same work, so a second run of the hooks must change nothing.
        def snapshot(sender: type[Integration], instance: Integration, **kwargs: Any) -> None:
            if instance.pk == integration.pk:
                at_delete.append(values())
                lifecycle.run_delete_hooks([instance])
                at_delete.append(values())

        pre_delete.connect(snapshot, sender=Integration, weak=False)
        try:
            IntegrationManager.any.with_source_rows().delete(self.team.id, integration.id, ignore_usages=True)
        finally:
            pre_delete.disconnect(snapshot, sender=Integration)

        expected: list[int | None] = [] if on_delete is models.CASCADE else [None]
        assert at_delete == [expected, expected]
        assert values() == expected
