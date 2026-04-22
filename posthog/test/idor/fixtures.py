"""
Fixture registry for the auto-IDOR test.

For viewsets whose models have required FKs or custom validation that
`build_minimal_instance` can't satisfy via field introspection alone,
register a factory here. A factory takes the victim team and returns a
model instance scoped to that team (or its parent org / the victim user).

Factories are keyed by Django model label (`app_label.ModelName`) so
this module doesn't hard-code module paths that rot as products move.
The key is `model_cls._meta.label`.

Keep factories minimal — just enough to get an instance into the DB
without tripping required-field or constraint validators. The IDOR test
only cares that a resource exists in the victim's team with a known pk.

When adding a new factory:
  1. Write it as a plain function `def foo_factory(team): ...`.
  2. Register it via `register_label_fixture("app_label.ModelName", foo_factory)`.
  3. Re-run `hogli test posthog/test/test_idor_coverage.py` and confirm
     the relevant test moves from SKIPPED to PASSED.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Optional

from django.db import models

from posthog.models.team import Team

IDORFixtureFactory = Callable[[Team], models.Model]

_REGISTRY_BY_LABEL: dict[str, IDORFixtureFactory] = {}


def register_label_fixture(label: str, factory: IDORFixtureFactory) -> None:
    """Associate a factory with a model, keyed by `app_label.ModelName`."""
    _REGISTRY_BY_LABEL[label] = factory


def get_fixture(model_cls: type[models.Model]) -> Optional[IDORFixtureFactory]:
    return _REGISTRY_BY_LABEL.get(model_cls._meta.label)


VICTIM_USER_EMAIL = "victim+idor@posthog.com"


def _victim_user():
    from posthog.models.user import User

    return User.objects.get(email=VICTIM_USER_EMAIL)


def _rand() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Factories — each is a small closure over `team`. Imports happen at call
# time to avoid polluting module-import side effects.
# ---------------------------------------------------------------------------


# Organization-scoped models ------------------------------------------------


def _org_domain_factory(team: Team) -> models.Model:
    from posthog.models.organization_domain import OrganizationDomain

    return OrganizationDomain.objects.create(organization=team.organization, domain=f"idor-{_rand()}.example.com")


register_label_fixture("posthog.OrganizationDomain", _org_domain_factory)


def _change_request_factory(team: Team) -> models.Model:
    import datetime

    from django.utils import timezone as django_timezone

    from posthog.approvals.models import ChangeRequest

    return ChangeRequest.objects.create(
        team=team,
        organization=team.organization,
        action_key="idor-test",
        resource_type="test",
        intent={},
        intent_display={},
        policy_snapshot={},
        expires_at=django_timezone.now() + datetime.timedelta(days=1),
    )


register_label_fixture("posthog.ChangeRequest", _change_request_factory)


def _approval_policy_factory(team: Team) -> models.Model:
    from posthog.approvals.models import ApprovalPolicy

    return ApprovalPolicy.objects.create(
        organization=team.organization,
        action_key=f"idor-policy-{_rand()}",
        approver_config={},
    )


register_label_fixture("posthog.ApprovalPolicy", _approval_policy_factory)


def _proxy_record_factory(team: Team) -> models.Model:
    from posthog.models.proxy_record import ProxyRecord

    return ProxyRecord.objects.create(
        organization=team.organization,
        domain=f"idor-{_rand()}.example.com",
    )


register_label_fixture("posthog.ProxyRecord", _proxy_record_factory)


def _org_integration_factory(team: Team) -> models.Model:
    from posthog.models.organization_integration import OrganizationIntegration

    return OrganizationIntegration.objects.create(
        organization=team.organization,
        kind="slack",
        integration_id=f"idor-{_rand()}",
        config={"test": True},
    )


register_label_fixture("posthog.OrganizationIntegration", _org_integration_factory)


def _notification_event_factory(team: Team) -> models.Model:
    from products.notifications.backend.models import NotificationEvent

    return NotificationEvent.objects.create(
        organization=team.organization,
        notification_type="generic",
        title="idor",
        target_type="user",
        target_id=f"idor-{_rand()}",
    )


register_label_fixture("notifications.NotificationEvent", _notification_event_factory)


# User-scoped models --------------------------------------------------------


def _file_system_shortcut_factory(team: Team) -> models.Model:
    from posthog.models.file_system.file_system_shortcut import FileSystemShortcut

    return FileSystemShortcut.objects.create(team=team, user=_victim_user(), path="idor-test-shortcut")


register_label_fixture("posthog.FileSystemShortcut", _file_system_shortcut_factory)


def _persisted_folder_factory(team: Team) -> models.Model:
    from posthog.models.file_system.persisted_folder import PersistedFolder

    return PersistedFolder.objects.create(
        team=team, user=_victim_user(), type="idor", protocol="idor://", path="idor-folder"
    )


register_label_fixture("posthog.PersistedFolder", _persisted_folder_factory)


def _user_product_list_factory(team: Team) -> models.Model:
    from posthog.models.file_system.user_product_list import UserProductList

    return UserProductList.objects.create(team=team, user=_victim_user(), product_path=f"idor-{_rand()}")


register_label_fixture("posthog.UserProductList", _user_product_list_factory)


# Insight-dependent models --------------------------------------------------


def _create_insight(team: Team):
    from posthog.models.insight import Insight

    return Insight.objects.create(team=team, name="idor-insight")


def _alert_factory(team: Team) -> models.Model:
    from posthog.models.alert import AlertConfiguration

    return AlertConfiguration.objects.create(
        team=team,
        insight=_create_insight(team),
        name="idor-alert",
        created_by=_victim_user(),
        config={"type": "TrendsAlertConfig", "series_index": 0},
        condition={"type": "absolute_value"},
        threshold=None,
    )


register_label_fixture("posthog.AlertConfiguration", _alert_factory)


def _threshold_factory(team: Team) -> models.Model:
    from posthog.models.alert import Threshold

    return Threshold.objects.create(team=team, insight=_create_insight(team), name="idor-threshold")


register_label_fixture("posthog.Threshold", _threshold_factory)


def _customer_journey_factory(team: Team) -> models.Model:
    from products.customer_analytics.backend.models.customer_journey import CustomerJourney

    return CustomerJourney.objects.create(team=team, insight=_create_insight(team), name="idor-journey")


register_label_fixture("customer_analytics.CustomerJourney", _customer_journey_factory)


# FeatureFlag-dependent models ---------------------------------------------


def _create_feature_flag(team: Team, suffix: str = ""):
    from posthog.models.feature_flag.feature_flag import FeatureFlag

    return FeatureFlag.objects.create(
        team=team,
        key=f"idor-ff-{_rand()}{suffix}",
        name="idor-ff",
        created_by=_victim_user(),
    )


def _experiment_factory(team: Team) -> models.Model:
    from products.experiments.backend.models.experiment import Experiment

    return Experiment.objects.create(team=team, feature_flag=_create_feature_flag(team, "-exp"), name="idor-experiment")


register_label_fixture("experiments.Experiment", _experiment_factory)


def _web_experiment_factory(team: Team) -> models.Model:
    from products.experiments.backend.models.web_experiment import WebExperiment

    return WebExperiment.objects.create(team=team, feature_flag=_create_feature_flag(team, "-web"), name="idor-web-exp")


register_label_fixture("experiments.WebExperiment", _web_experiment_factory)


# BatchExport chain --------------------------------------------------------


def _create_batch_export(team: Team):
    from posthog.batch_exports.models import BatchExport, BatchExportDestination

    destination = BatchExportDestination.objects.create(type="NoOp", config={})
    return BatchExport.objects.create(
        team=team, destination=destination, name="idor-batch-export", interval="every 5 minutes"
    )


def _batch_export_factory(team: Team) -> models.Model:
    return _create_batch_export(team)


register_label_fixture("posthog.BatchExport", _batch_export_factory)


def _batch_export_run_factory(team: Team) -> models.Model:
    from posthog.batch_exports.models import BatchExportRun

    return BatchExportRun.objects.create(
        batch_export=_create_batch_export(team),
        status="Completed",
        data_interval_start="2024-01-01 00:00:00Z",
        data_interval_end="2024-01-01 00:05:00Z",
    )


register_label_fixture("posthog.BatchExportRun", _batch_export_run_factory)


def _batch_export_backfill_factory(team: Team) -> models.Model:
    from posthog.batch_exports.models import BatchExportBackfill

    return BatchExportBackfill.objects.create(
        team=team,
        batch_export=_create_batch_export(team),
        status="Completed",
        start_at="2024-01-01 00:00:00Z",
        end_at="2024-01-01 01:00:00Z",
    )


register_label_fixture("posthog.BatchExportBackfill", _batch_export_backfill_factory)


def _batch_import_factory(team: Team) -> models.Model:
    from posthog.models.batch_imports import BatchImport

    # `secrets` is an EncryptedJSONStringField — expects a string, not a dict.
    return BatchImport.objects.create(
        team=team, status="running", secrets="{}", import_config={"source": {"type": "idor"}}
    )


register_label_fixture("posthog.BatchImport", _batch_import_factory)


# Plugin / PluginConfig chain ----------------------------------------------


def _create_plugin(team: Team):
    from posthog.models.plugin import Plugin

    return Plugin.objects.create(organization=team.organization, name=f"idor-plugin-{_rand()}", plugin_type="custom")


def _plugin_config_factory(team: Team) -> models.Model:
    from posthog.models.plugin import PluginConfig

    return PluginConfig.objects.create(team=team, plugin=_create_plugin(team), order=0, config={})


register_label_fixture("posthog.PluginConfig", _plugin_config_factory)


# Dataset chain ------------------------------------------------------------


def _dataset_item_factory(team: Team) -> models.Model:
    from products.llm_analytics.backend.models.datasets import Dataset, DatasetItem

    dataset = Dataset.objects.create(team=team, name="idor-dataset")
    return DatasetItem.objects.create(team=team, dataset=dataset, input={})


register_label_fixture("llm_analytics.DatasetItem", _dataset_item_factory)


# Task chain ---------------------------------------------------------------


def _create_task(team: Team):
    from products.tasks.backend.models import Task

    return Task.objects.create(team=team, title=f"idor-task-{_rand()}")


def _task_automation_factory(team: Team) -> models.Model:
    from products.tasks.backend.models import TaskAutomation

    # TaskAutomation has no team field; team is derived from OneToOneField `task`.
    return TaskAutomation.objects.create(task=_create_task(team), cron_expression="0 * * * *")


register_label_fixture("tasks.TaskAutomation", _task_automation_factory)


def _task_run_factory(team: Team) -> models.Model:
    from products.tasks.backend.models import TaskRun

    return TaskRun.objects.create(team=team, task=_create_task(team), status="pending")


register_label_fixture("tasks.TaskRun", _task_run_factory)


# DAG / Node / Edge chain (data_modeling) ----------------------------------


def _create_dag(team: Team):
    from products.data_modeling.backend.models.dag import DAG

    return DAG.objects.create(team=team, name=f"idor-dag-{_rand()}")


def _create_node(team: Team, dag=None):
    from products.data_modeling.backend.models.node import Node

    return Node.objects.create(team=team, dag=dag or _create_dag(team), name=f"idor-node-{_rand()}")


def _node_factory(team: Team) -> models.Model:
    return _create_node(team)


register_label_fixture("data_modeling.Node", _node_factory)


def _edge_factory(team: Team) -> models.Model:
    from products.data_modeling.backend.models.edge import Edge

    dag = _create_dag(team)
    source = _create_node(team, dag=dag)
    target = _create_node(team, dag=dag)
    return Edge.objects.create(team=team, source=source, target=target, dag=dag)


register_label_fixture("data_modeling.Edge", _edge_factory)


# External Data Source chain ----------------------------------------------


def _external_data_schema_factory(team: Team) -> models.Model:
    from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
    from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

    source = ExternalDataSource.objects.create(
        team=team, source_type="Stripe", source_id=f"idor-{_rand()}", job_inputs={}
    )
    return ExternalDataSchema.objects.create(team=team, source=source, name="idor-schema")


register_label_fixture("data_warehouse.ExternalDataSchema", _external_data_schema_factory)


# Evaluation chain ---------------------------------------------------------


def _create_evaluation(team: Team):
    from products.llm_analytics.backend.models.evaluations import Evaluation

    return Evaluation.objects.create(team=team, name="idor-eval", evaluation_type="llm_judge", output_type="numeric")


def _evaluation_report_factory(team: Team) -> models.Model:
    from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport

    return EvaluationReport.objects.create(team=team, evaluation=_create_evaluation(team))


register_label_fixture("llm_analytics.EvaluationReport", _evaluation_report_factory)


# Review queue chain -------------------------------------------------------


def _review_queue_item_factory(team: Team) -> models.Model:
    from products.llm_analytics.backend.models.review_queues import ReviewQueue, ReviewQueueItem

    queue = ReviewQueue.objects.create(team=team, name=f"idor-queue-{_rand()}")
    return ReviewQueueItem.objects.create(team=team, queue=queue, trace_id=f"idor-{_rand()}")


register_label_fixture("llm_analytics.ReviewQueueItem", _review_queue_item_factory)


# Event schema -------------------------------------------------------------


def _event_schema_factory(team: Team) -> models.Model:
    from products.event_definitions.backend.models.event_definition import EventDefinition
    from products.event_definitions.backend.models.schema import EventSchema, SchemaPropertyGroup

    event_def = EventDefinition.objects.create(team=team, name=f"idor-event-{_rand()}")
    group = SchemaPropertyGroup.objects.create(team=team, name=f"idor-group-{_rand()}")
    return EventSchema.objects.create(event_definition=event_def, property_group=group)


register_label_fixture("event_definitions.EventSchema", _event_schema_factory)


# Session recording external reference ------------------------------------


def _session_recording_external_ref_factory(team: Team) -> models.Model:
    from posthog.models.integration import Integration
    from posthog.session_recordings.models.session_recording import SessionRecording
    from posthog.session_recordings.models.session_recording_external_reference import SessionRecordingExternalReference

    # No team FK on this model; team is derived from session_recording.team.
    recording = SessionRecording.objects.create(team=team, session_id=f"idor-{_rand()}")
    integration = Integration.objects.create(team=team, kind="slack", config={})
    return SessionRecordingExternalReference.objects.create(
        session_recording=recording, integration=integration, external_context={}
    )


register_label_fixture("posthog.SessionRecordingExternalReference", _session_recording_external_ref_factory)
