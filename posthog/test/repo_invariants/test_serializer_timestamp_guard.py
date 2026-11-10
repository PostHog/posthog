"""Guard against writable server-owned timestamps on API serializers.

A serializer that a write route (POST, PUT or PATCH) uses must not expose a
`DateTimeField` for writing when the backend owns the value. The route then lets a
client overwrite something the product reads back as server truth.
`FeatureFlagSerializer` carried that hole on `created_at` and `last_called_at` for
years, because a `ModelSerializer` builds every concrete column as writable unless
something says otherwise.

Django has no declarative marker for "the server owns this column", and no property
of the column reliably stands in for one. `auto_now` and a non-null `default` are
evidence of self-filling, not of ownership: `published_at = DateTimeField(default=
timezone.now)` is a field a client is meant to set. A naming convention guesses in
both directions at once, missing `expires_at` while flagging a `last_sent_at` the
API offers on purpose.

So ownership is not inferred. Every writable `DateTimeField` a write route exposes
must appear in `REVIEWED_WRITABLE` with a reason a person wrote. An entry whose
reason starts with `TODO` is a hole the owning team still has to close; every other
entry records a field a client is supposed to set, and why.

The cost is one line per field. The benefit is that a new writable timestamp cannot
reach master unnoticed, whatever the column is called and however it is declared.

To close a hole on a field the serializer generates from the model, put it in
`read_only_fields` on `Meta`, then delete its entry here. A field the serializer
declares needs `read_only=True` on the declaration itself, because DRF ignores
`read_only_fields` for a declared field.

A plain `Serializer` with no `Meta.model` is checked the same way. It has no column
to read, so only the view's own code says whether the value becomes server truth,
and its reason in `REVIEWED_WRITABLE` has to say which.

One shape is out of scope, so "every writable timestamp is reviewed" means every
one this guard can see, not every one the API has: only top-level fields are
compared. A timestamp inside a nested writable serializer is not reached.

The failure message lists every violation:

    pytest posthog/test/repo_invariants/test_serializer_timestamp_guard.py
"""

import ast
import sys
import inspect
import textwrap
import functools
import importlib
from collections.abc import Sequence
from typing import Any, TypeGuard

from django.core.exceptions import FieldDoesNotExist
from django.db import models

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, viewsets
from rest_framework.fields import empty
from rest_framework.generics import GenericAPIView

# DRF's enumerator, not the drf-spectacular subclass, because the subclass runs
# `preprocess_exclude_path_format`, which drops every INTERNAL and undocumented route
# from the schema. Those routes still accept writes, so the guard has to see them.
from rest_framework.schemas.generators import EndpointEnumerator

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})

# The ways a view names the serializer it hands a write request. One entry per distinct
# mechanism, because `test_every_discovery_path_finds_something` asserts each still
# finds something, and a mechanism folded into another's bucket can die unnoticed.
SERIALIZER_SOURCES = (
    "serializer_class attribute",
    "serializer lookup table",
    "get_serializer_class return",
    "get_serializer_class local",
)
REQUEST_BODY_SOURCE = "@extend_schema(request=...)"

# `module.Serializer.field` -> why this timestamp is writable on a write route.
# A reason starting with `TODO` marks a hole the owning team still has to close;
# every other entry records a value a client is supposed to set. Nothing is inferred,
# so a field missing from here fails the build until a person classifies it.
REVIEWED_WRITABLE: dict[str, str] = {
    "posthog.api.personal_api_key.PersonalAPIKeySerializer.expires_at": "Client picks when the key stops working, or null for never; a past date is rejected",
    "products.cdp.backend.api.hog_function.HogFunctionSerializer.base_updated_at": "Optimistic-concurrency guard: the client echoes the timestamp it loaded, and the view pops it before save",
    "products.managed_migrations.backend.api.batch_imports.BatchImportDateRangeSourceCreateSerializer.start_date": "Client picks the import window; write-only input, never stored on the model",
    "products.managed_migrations.backend.api.batch_imports.BatchImportDateRangeSourceCreateSerializer.end_date": "Client picks the import window; write-only input, never stored on the model",
    "posthog.api.advanced_activity_logs.viewset.ActivityLogFlatExportSerializer.created_at": "TODO: server-owned audit timestamp, make read-only",
    "posthog.api.advanced_activity_logs.viewset.ActivityLogSerializer.created_at": "TODO: server-owned audit timestamp, make read-only",
    "posthog.api.event_definition.EventDefinitionSerializer.created_at": "TODO: server-owned, set when ingestion first sees the event",
    "posthog.api.event_definition.EventDefinitionSerializer.last_seen_at": "TODO: server-owned ingestion telemetry, make read-only",
    "posthog.api.health_issue.HealthIssueSerializer.snoozed_until": "TODO: server-derived. SnoozeDurationField accepts only a relative duration such as '7d' and computes the stored instant",
    "posthog.api.my_notifications.MyNotificationsSerializer.created_at": "TODO: server-owned activity log timestamp, make read-only",
    "posthog.session_recordings.session_recording_api.SessionRecordingSharedSerializer.end_time": "TODO: server-owned, derived from the ingested replay events",
    "posthog.session_recordings.session_recording_api.SessionRecordingSharedSerializer.start_time": "TODO: server-owned, derived from the ingested replay events",
    "products.actions.backend.presentation.views.action.ActionSerializer.last_calculated_at": "TODO: server-owned, written by the action calculation job",
    "products.actions.backend.presentation.views.action.ActionSerializer.pinned_at": "TODO: server-derived on pin. update() discards the supplied value and stores its own now(); only the null that unpins is the client's",
    "products.alerts.backend.presentation.views.alert.AlertSerializer.snoozed_until": "TODO: server-derived. The client sends a relative date string and update() resolves it to the stored instant",
    "products.billing_alerts.backend.presentation.serializers.BillingAlertConfigurationSerializer.snoozed_until": "Client-set instant: a plain DateTimeField that ModelSerializer writes to the column unchanged, with no relative-duration parsing on this path",
    "products.conversations.backend.api.tickets.TicketSerializer.sla_due_at": "Client or a workflow sets the SLA deadline, and null clears it",
    "products.conversations.backend.api.tickets.TicketSerializer.snoozed_until": "Client-set instant: the ticket action assigns validated_data['snoozed_until'] to ticket.snoozed_until, with no relative-duration parsing on this path",
    "products.conversations.backend.api.tickets.TicketUpdateRequestSerializer.sla_due_at": "Client or a workflow sets the SLA deadline, and null clears it",
    "products.conversations.backend.api.tickets.TicketUpdateRequestSerializer.snoozed_until": "Client-set instant: the ticket action assigns validated_data['snoozed_until'] to ticket.snoozed_until, with no relative-duration parsing on this path",
    "products.dashboards.backend.api.dashboard.DashboardSerializer.last_refresh": "The frontend PATCHes successful forced-refresh completion so reopening the dashboard retains its shared cooldown",
    "products.experiments.backend.presentation.serializers.ExperimentSerializer.end_date": "Client stops the experiment by setting this",
    "products.experiments.backend.presentation.serializers.ExperimentSerializer.start_date": "Client launches the experiment by setting this",
    "products.experiments.backend.presentation.serializers.ExperimentWriteSerializer.end_date": "Client stops the experiment by setting this",
    "products.experiments.backend.presentation.serializers.ExperimentWriteSerializer.start_date": "Client launches the experiment by setting this",
    "products.experiments.backend.presentation.web_experiments.WebExperimentsAPISerializer.created_at": "TODO: server-owned creation timestamp, make read-only",
    "products.feature_flags.backend.api.scheduled_change.ScheduledChangeSerializer.end_date": "Client picks when a recurring schedule stops",
    "products.feature_flags.backend.api.scheduled_change.ScheduledChangeSerializer.scheduled_at": "Client picks when the change is applied",
    "products.groups.backend.presentation.views.GroupTypeSerializer.created_at": "TODO: server-owned, the model sets it on creation itself",
    "products.logs.backend.presentation.views.alerts_api.LogsAlertConfigurationSerializer.snooze_until": "Client-set instant: update() pops snooze_until and assigns it to instance.snooze_until, with no relative-duration parsing on this path",
    "products.product_tours.backend.api.product_tour.ProductTourSerializer.end_date": "Client schedules when the tour stops",
    "products.product_tours.backend.api.product_tour.ProductTourSerializer.start_date": "Client schedules when the tour starts",
    "products.product_tours.backend.api.product_tour.ProductTourSerializerCreateUpdateOnly.end_date": "Client schedules when the tour stops",
    "products.product_tours.backend.api.product_tour.ProductTourSerializerCreateUpdateOnly.start_date": "Client schedules when the tour starts",
    "products.reminders.backend.api.reminder.ReminderSerializer.end_date": "Client picks when a recurring reminder stops",
    "products.reminders.backend.api.reminder.ReminderSerializer.scheduled_at": "Client picks when a one-off reminder fires",
    "products.replay_vision.backend.api.observations.ReplayObservationSerializer.completed_at": "TODO: server-owned, written by the evaluation workflow",
    "products.replay_vision.backend.api.observations.ReplayObservationSerializer.started_at": "TODO: server-owned, written by the evaluation workflow",
    "products.replay_vision.backend.api.vision_alerts.VisionAlertConfigurationSerializer.snooze_until": "Client-set instant: update() pops snooze_until and assigns it to instance.snooze_until, with no relative-duration parsing on this path",
    "products.surveys.backend.api.survey.SurveySerializer.current_iteration_start_date": "TODO: server-owned, the iteration task advances it",
    "products.surveys.backend.api.survey.SurveySerializer.end_date": "Client stops the survey by setting this",
    "products.surveys.backend.api.survey.SurveySerializer.response_sampling_start_date": "Client sets when response sampling starts",
    "products.surveys.backend.api.survey.SurveySerializer.start_date": "Client launches the survey by setting this",
    "products.surveys.backend.api.survey.SurveySerializerCreateUpdateOnly.current_iteration_start_date": "TODO: server-owned, the iteration task advances it",
    "products.surveys.backend.api.survey.SurveySerializerCreateUpdateOnly.end_date": "Client stops the survey by setting this",
    "products.surveys.backend.api.survey.SurveySerializerCreateUpdateOnly.response_sampling_start_date": "Client sets when response sampling starts",
    "products.surveys.backend.api.survey.SurveySerializerCreateUpdateOnly.start_date": "Client launches the survey by setting this",
    "products.surveys.backend.api.survey.SurveySerializerCreateUpdateOnlySchema.current_iteration_start_date": "TODO: server-owned, the iteration task advances it",
    "products.surveys.backend.api.survey.SurveySerializerCreateUpdateOnlySchema.end_date": "Client stops the survey by setting this",
    "products.surveys.backend.api.survey.SurveySerializerCreateUpdateOnlySchema.response_sampling_start_date": "Client sets when response sampling starts",
    "products.surveys.backend.api.survey.SurveySerializerCreateUpdateOnlySchema.start_date": "Client launches the survey by setting this",
    # Plain serializers with no Meta.model. "Response shape only" marks a serializer
    # that a write route names but never validates a request body through.
    "posthog.api.personal_api_key.PersonalAPIKeyRollSerializer.expires_at": "Client picks the rolled key's new expiry, or null for never; roll() copies it to the key, a past date is rejected",
    "posthog.api.user_integration.UserGitHubIntegrationItemSerializer.created_at": "TODO: server-owned, response shape only; no write route validates a body through it, only list builds items from rows; make read-only",
    "posthog.api.user_integration.UserGitHubIntegrationItemSerializer.needs_reauthorization_at": "TODO: server-owned, response shape only; set when GitHub rejects the credentials, no write route reads it; make read-only",
    "posthog.api.user_push_token.UserPushTokenItemSerializer.created_at": "TODO: server-owned, response shape only; register reads the body through UserPushTokenRegisterRequestSerializer; make read-only",
    "posthog.api.user_push_token.UserPushTokenItemSerializer.last_seen_at": "TODO: server-owned, response shape only; UserPushToken.register refreshes it, the body is read through the register serializer; make read-only",
    "products.ai_observability.backend.api.datasets.DatasetItemCreateSerializer.source_timestamp": "Client sends the timestamp of the source trace event; passed to create_dataset_item to find the event-backed trace",
    "products.ai_observability.backend.api.evaluation_backfills.EvaluationBackfillRequestSerializer.window_end": "Client picks the backfill window end; clamped to now and the retention period, then passed to the backfill workflow",
    "products.ai_observability.backend.api.evaluation_backfills.EvaluationBackfillRequestSerializer.window_start": "Client picks the backfill window start; clamped to the retention period, then passed to the backfill workflow",
    "products.ai_observability.backend.api.evaluation_runs.EvaluationRunRequestSerializer.timestamp": "Client sends the target event timestamp; used only as a ClickHouse lookup key (toDate match) for that event",
    "products.ai_observability.backend.api.offline_experiment_serializers.ExperimentSubmissionSerializer.started_at": "Client reports when the offline experiment run started; stored with the experiment, help text says caller-supplied",
    "products.ai_observability.backend.presentation.views.TraceExportCreateSerializer.timestamp_hint": "Client hint of when the trace happened; range-checked, passed to create_trace_export to load old traces",
    "products.alerts_platform.backend.presentation.views.platform_alert.PlatformAlertGroupSnoozeSerializer.snooze_until": "Client picks when the group snooze ends, or null to clear; passed to snooze_group, help text limits it to 30 days ahead",
    "products.annotations.backend.presentation.serializers.AnnotationSerializer.date_marker": "Client picks when the annotation happened, to place it on charts; to_write() passes it to the facade",
    "products.batch_exports.backend.presentation.views.batch_export.backfills.BatchExportBackfillSerializer.adjusted_start_at": "TODO: response shape only; create reads start_at and end_at raw from request.data and never validates through this serializer, make read-only",
    "products.batch_exports.backend.presentation.views.batch_export.backfills.BatchExportBackfillSerializer.end_at": "TODO: response shape only; create reads start_at and end_at raw from request.data and never validates through this serializer, make read-only",
    "products.batch_exports.backend.presentation.views.batch_export.backfills.BatchExportBackfillSerializer.finished_at": "TODO: response shape only; create reads start_at and end_at raw from request.data and never validates through this serializer, make read-only",
    "products.batch_exports.backend.presentation.views.batch_export.backfills.BatchExportBackfillSerializer.start_at": "TODO: response shape only; create reads start_at and end_at raw from request.data and never validates through this serializer, make read-only",
    "products.batch_exports.backend.presentation.views.batch_export.exports.BatchExportSerializer.end_at": "Client sets when the export schedule stops triggering runs; create and update pass it to the facade and the model",
    "products.batch_exports.backend.presentation.views.batch_export.exports.BatchExportSerializer.last_paused_at": "TODO: server-owned, service.py sets it on pause; a client value is stored by create/update and unpause uses it as the backfill start; make read-only",
    "products.batch_exports.backend.presentation.views.batch_export.exports.BatchExportSerializer.start_at": "Client sets the time before which the export does not run; create and update pass it to the facade and the model",
    "products.batch_exports.backend.presentation.views.batch_export.runs.BatchExportRunSerializer.data_interval_end": "TODO: server-owned, response shape only; the run viewset has no create or update, retry and cancel read no body; make read-only",
    "products.batch_exports.backend.presentation.views.batch_export.runs.BatchExportRunSerializer.data_interval_start": "TODO: server-owned, response shape only; the run viewset has no create or update, retry and cancel read no body; make read-only",
    "products.batch_exports.backend.presentation.views.batch_export.runs.BatchExportRunSerializer.finished_at": "TODO: server-owned, response shape only; the run viewset has no create or update, retry and cancel read no body; make read-only",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadBatchExportOnDemandSerializer.data_interval_end": "Client picks the export window end; validated for order, range and not in the future, then passed to the on-demand export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadBatchExportOnDemandSerializer.data_interval_start": "Client picks the export window start; validated for order, range and not in the future, then passed to the on-demand export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadCountRowsRequestSerializer.data_interval_end": "Client picks the window end for the row count; validated, then passed to the count query",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadCountRowsRequestSerializer.data_interval_start": "Client picks the window start for the row count; validated, then passed to the count query",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadEventsRequestSerializer.data_interval_end": "Client picks the events export window end; request input for the on-demand export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadEventsRequestSerializer.data_interval_start": "Client picks the events export window start; request input for the on-demand export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadHogQLRequestSerializer.data_interval_end": "Client picks the window end that fills the HogQL {data_interval_end} placeholder; request input for the export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadHogQLRequestSerializer.data_interval_start": "Client picks the window start that fills the HogQL {data_interval_start} placeholder; request input for the export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadPersonsRequestSerializer.data_interval_end": "Client picks the persons export window end; request input for the on-demand export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadPersonsRequestSerializer.data_interval_start": "Client picks the persons export window start; request input for the on-demand export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadSessionsRequestSerializer.data_interval_end": "Client picks the sessions export window end; request input for the on-demand export",
    "products.batch_exports.backend.presentation.views.file_download.FileDownloadSessionsRequestSerializer.data_interval_start": "Client picks the sessions export window start; request input for the on-demand export",
    "products.business_knowledge.backend.api.serializers.PlaygroundChatSerializer.created_at": "TODO: server-owned, response shape only; create takes no body and ask reads SandboxQuestionSerializer; make read-only",
    "products.business_knowledge.backend.api.serializers.PlaygroundChatSerializer.updated_at": "TODO: server-owned, response shape only; create takes no body and ask reads SandboxQuestionSerializer; make read-only",
    "products.customer_analytics.backend.presentation.views.customer_tasks.CustomerTaskCreateSerializer.due_at": "Client sets the task deadline; create passes validated data into CreateCustomerTaskInput",
    "products.customer_analytics.backend.presentation.views.customer_tasks.CustomerTaskUpdateSerializer.due_at": "Client sets or clears the task deadline; update tracks it with due_at_provided and passes it to the facade",
    "products.customer_analytics.backend.presentation.views.serializers.AccountSerializer.churned_at": "Client records when the account churned, or null; create and update pass it to the facade, update only when sent",
    "products.customer_analytics.backend.presentation.views.serializers.AccountSerializer.ignored_at": "Client or Track Rules mark when the account was ignored, null means tracked; create and update pass it to the facade",
    "products.customer_analytics.backend.presentation.views.workflow_customer_tasks.WorkflowCustomerTaskCreateSerializer.due_at": "The workflow action sets the task deadline; the service-token endpoint passes it into CreateCustomerTaskInput",
    "products.data_catalog.backend.presentation.serializers.MetricApproveRequestSerializer.expected_updated_at": "Optimistic-concurrency echo: the approver sends the updated_at it saw, and the view passes it so a changed metric returns 409",
    "products.error_tracking.backend.presentation.views.issues.ErrorTrackingIssueReadSerializer.first_seen": "TODO: server-owned, response shape only; update reads the body through ErrorTrackingIssueWriteSerializer, make read-only",
    "products.error_tracking.backend.presentation.views.releases.ErrorTrackingReleaseSerializer.created_at": "TODO: server-owned, response shape only; create and update read request.data through their own request serializers, make read-only",
    "products.error_tracking.backend.presentation.views.stack_frames.ErrorTrackingStackFrameSerializer.created_at": "TODO: server-owned, response shape only; batch_get reads only raw_ids and symbol_set from the body, make read-only",
    "products.error_tracking.backend.presentation.views.symbol_sets.ErrorTrackingSymbolSetSerializer.created_at": "TODO: server-owned, response shape only; update returns the unchanged row and uploads use other serializers, make read-only",
    "products.error_tracking.backend.presentation.views.symbol_sets.ErrorTrackingSymbolSetSerializer.last_used": "TODO: server-owned, response shape only; update returns the unchanged row and uploads use other serializers, make read-only",
    "products.feature_flags.backend.api.feature_flag.FeatureFlagTestEvaluationRequestSerializer.timestamp": "Client picks the point in time to test a flag against; request input for test_evaluation, never stored",
    "products.logs.backend.presentation.views.explain.ExplainRequestSerializer.timestamp": "Client sends the timestamp of the log entry; used for the log lookup and the cache key, never stored on a model",
    "products.notifications.backend.presentation.serializers.NotificationEventSerializer.created_at": "TODO: server-owned, response shape only; the mark and archive routes read ids from the body, never this serializer, make read-only",
    "products.notifications.backend.presentation.serializers.NotificationEventSerializer.read_at": "TODO: server-owned, response shape only; the mark read routes set it server side and never read this serializer, make read-only",
    "products.replay_vision.backend.api.backfills.BackfillCreateSerializer.window_end": "Client picks the backfill window; clamped to now minus settle time, stored on the backfill and passed to the backfill workflow",
    "products.replay_vision.backend.api.backfills.BackfillCreateSerializer.window_start": "Client picks the backfill window; stored on the backfill record and passed to the backfill workflow",
    "products.replay_vision.backend.api.backfills.BackfillWindowSerializer.window_end": "Client picks the window to estimate; clamped to now minus settle time, only used to count sessions, never stored",
    "products.replay_vision.backend.api.backfills.BackfillWindowSerializer.window_start": "Client picks the window to estimate; only used to count sessions, never stored",
    "products.replay_vision.backend.api.observation_requests.ObservationRequestSerializer.created_at": "TODO: server-owned, response shape only; create reads the body through CreateObservationRequestSerializer, make read-only",
    "products.review_hog.backend.presentation.views.reviews.ReviewRecentReviewSerializer.last_run_at": "TODO: server-owned, response shape only; the trigger route reads the body through ReviewTriggerRequestSerializer, make read-only",
    "products.signals.backend.presentation.onboarding.InboxOnboardingStateSerializer.completed_at": "TODO: server-owned, response shape only; write routes read the body through InboxOnboardingDraftSerializer, make read-only",
    "products.signals.backend.scout_harness.serializers.CreateReportCheckRequestSerializer.expires_at": "Scout picks when the check stops; validated to be after the first run and within the horizon, then passed to create_report_check",
    "products.signals.backend.scout_harness.serializers.CreateReportCheckRequestSerializer.next_run_at": "Scout picks when the check first runs; validated as future and within the horizon, then passed to create_report_check",
    "products.signals.backend.scout_harness.serializers.RememberRequestSerializer.expires_at": "Client sets when a memory expires; a past or unparseable value is dropped, and omitting it clears the expiry",
    "products.signals.backend.scout_harness.serializers.ScoutNoteCreateRequestSerializer.expires_at": "Client sets when a steering note retires; a past or unparseable value is dropped, passed to leave_note",
    "products.signals.backend.views.PauseUntilRequestSerializer.timestamp": "Client picks when the grouping pipeline resumes; request input passed to the pause_until workflow call",
    "products.subscriptions.backend.presentation.views.SubscriptionSerializer.start_date": "Client picks when deliveries start; inherited from SubscriptionWriteSerializer, which the view uses for writes, stored on the subscription",
    "products.subscriptions.backend.presentation.views.SubscriptionSerializer.until_date": "Client picks when deliveries stop, or null for never; inherited from SubscriptionWriteSerializer, stored on the subscription",
    "products.subscriptions.backend.presentation.views.SubscriptionWriteSerializer.start_date": "Client picks when deliveries start; to_write passes it to the facade, which stores it and anchors the recurrence",
    "products.subscriptions.backend.presentation.views.SubscriptionWriteSerializer.until_date": "Client picks when deliveries stop, or null for never; to_write passes it to the facade, which stores it",
    "products.tasks.backend.presentation.serializers.ChannelFeedMessageSerializer.created_at": "TODO: server-owned, response shape only; create reads the body through ChannelFeedMessageWriteSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.ChannelFeedMessageWriteSerializer.created_at": "Client orders a burst of feed posts; validated to within 10 min of now, then stored as ChannelFeedMessage.created_at",
    "products.tasks.backend.presentation.serializers.ChannelSerializer.created_at": "TODO: server-owned, response shape only; create and update read the body through ChannelWriteSerializer and ChannelUpdateSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.ClaudeTaskRunCreateSchemaSerializer.scheduled_at": "Client picks the earliest run start (future, within 30 days); schema-only twin, view validates with TaskRunCreateRequestSerializer",
    "products.tasks.backend.presentation.serializers.CodexTaskRunCreateSchemaSerializer.scheduled_at": "Client picks the earliest run start (future, within 30 days); schema-only twin, view validates with TaskRunCreateRequestSerializer",
    "products.tasks.backend.presentation.serializers.TaskActivitySerializer.activity_at": "TODO: server-owned, response shape only; the only write route (mark read) uses TaskActivityMarkReadSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskCreateSerializer.scheduled_at": "Client picks the earliest start of the first run; used only when start_run is set, then passed into run creation",
    "products.tasks.backend.presentation.serializers.TaskRunCreateRequestSerializer.scheduled_at": "Client picks the earliest run start (future, within 30 days); passed to the facade, which creates the run NOT_STARTED until then",
    "products.tasks.backend.presentation.serializers.TaskRunDetailSerializer.completed_at": "TODO: server-owned, response shape only; run PATCH reads the body through TaskRunUpdateSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskRunDetailSerializer.created_at": "TODO: server-owned, response shape only; run PATCH reads the body through TaskRunUpdateSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskRunDetailSerializer.scheduled_at": "TODO: server-owned, response shape only; run create reads the body through TaskRunCreateRequestSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskRunDetailSerializer.updated_at": "TODO: server-owned, response shape only; run PATCH reads the body through TaskRunUpdateSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskRunResumeRequestSchemaSerializer.scheduled_at": "Client picks the earliest run start (future, within 30 days); schema-only variant, view validates with TaskRunCreateRequestSerializer",
    "products.tasks.backend.presentation.serializers.TaskSerializer.archived_at": "TODO: server-owned, response shape only; create and update read the body through TaskCreateSerializer and TaskWriteSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskSerializer.created_at": "TODO: server-owned, response shape only; create and update read the body through TaskCreateSerializer and TaskWriteSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskSerializer.last_activity_at": "TODO: server-owned, response shape only; create and update read the body through TaskCreateSerializer and TaskWriteSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskSerializer.last_client_at": "TODO: server-owned, response shape only; create and update read the body through TaskCreateSerializer and TaskWriteSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskSerializer.updated_at": "TODO: server-owned, response shape only; create and update read the body through TaskCreateSerializer and TaskWriteSerializer, make read-only",
    "products.tasks.backend.presentation.serializers.TaskThreadMessageSerializer.created_at": "TODO: server-owned, response shape only; thread create reads the body through TaskThreadMessageWriteSerializer (content only), make read-only",
    "products.tasks.backend.presentation.serializers.TaskThreadMessageSerializer.forwarded_to_agent_at": "TODO: server-owned, response shape only; thread create reads the body through TaskThreadMessageWriteSerializer (content only), make read-only",
    "products.tracing.backend.presentation.views._TracingErrorCountsRequestSerializer.dateFrom": "Client picks the start of the lookup window; request input for the error count query, never stored",
    "products.tracing.backend.presentation.views._TracingErrorCountsRequestSerializer.dateTo": "Client picks the end of the lookup window; request input for the error count query, never stored",
    "products.visual_review.backend.presentation.serializers.QuarantineInputSerializer.expires_at": "Client picks when the quarantine lifts itself, or null for no expiry; MCP callers get a capped expiry",
    "products.visual_review.backend.presentation.serializers.RunSerializer.approved_at": "TODO: server-owned, response shape only; complete and approve read the body through their own input serializers, make read-only",
    "products.visual_review.backend.presentation.serializers.RunSerializer.completed_at": "TODO: server-owned, response shape only; complete reads the body through CompleteRunInputSerializer, make read-only",
    "products.visual_review.backend.presentation.serializers.RunSerializer.created_at": "TODO: server-owned, response shape only; no route validates a body through RunSerializer, make read-only",
    "products.wizard.backend.presentation.scans.serializers.RecordWizardScanRequestSerializer.scanned_at": "Wizard stamps the scan time with its own clock; a value more than a day in the future is rejected, then stored on the scan",
    "products.wizard.backend.presentation.sessions.serializers.UpsertWizardSessionRequestSerializer.started_at": "Wizard sends its own start time, also encoded in session_id; passed to the upsert and stored on the session",
    "products.workflows.backend.presentation.views.hog_flow.HogFlowActionEmailUpdateSerializer.base_updated_at": "Optimistic-concurrency guard: the client echoes the updated_at it loaded; the view passes it to edit_workflow_content to detect a stale edit",
    "products.workflows.backend.presentation.views.hog_flow.HogFlowGraphUpdateSerializer.base_updated_at": "Optimistic-concurrency guard: the client echoes the updated_at it loaded; the view passes it to edit_workflow_content to detect a stale edit",
    "products.workflows.backend.presentation.views.hog_flow.HogFlowRevisionRestoreRequestSerializer.expected_draft_updated_at": "Optimistic-concurrency guard: the client echoes the draft_updated_at it confirmed; restore_revision returns 409 on a mismatch",
    "products.workflows.backend.presentation.views.hog_flow.HogFlowScheduleSerializer.starts_at": "Client picks when the schedule starts; create_schedule stores it and uses it to compute the next runs from the RRULE",
    "products.workflows.backend.presentation.views.hog_flow.WorkflowProposalApproveRequestSerializer.expected_draft_updated_at": "Optimistic-concurrency guard: the client echoes the draft_updated_at it confirmed; approve_proposal returns 409 on a mismatch",
    "products.workflows.backend.presentation.views.push_token_imports.PushTokenImportSerializer.created_at": "TODO: server-owned, response shape only; create reads the body through PushTokenImportCreateSerializer, make read-only",
    "products.workflows.backend.presentation.views.push_token_imports.PushTokenImportSerializer.finished_at": "TODO: server-owned, response shape only; create reads the body through PushTokenImportCreateSerializer, make read-only",
}

# Views and serializers the guard cannot read, each with a reason. An entry hides part
# of a write route, so this stays empty unless something genuinely cannot be resolved.
UNCHECKED: dict[str, str] = {}

# Serializers that only dynamic selection reaches. They are the regressions this file
# exists to prevent, so discovery is asserted to still find them.
HARD_TO_DISCOVER = {
    "products.product_analytics.backend.presentation.insight.MCPInsightSerializer": (
        "chosen by get_serializer_class only when the x-posthog-client request header is mcp"
    ),
    "ee.api.ee_event_definition.EnterpriseEventDefinitionSerializer": (
        "assigned to a local inside get_serializer_class from an import made in the function body"
    ),
}


def _dotted_name(obj: type) -> str:
    return f"{obj.__module__}.{obj.__qualname__}"


def _is_serializer(obj: Any) -> TypeGuard[type[serializers.BaseSerializer]]:
    return isinstance(obj, type) and issubclass(obj, serializers.BaseSerializer)


def _resolve(expression: ast.expr, scope: dict[str, Any], view_class: type) -> list[Any]:
    """Every object an expression in a `get_serializer_class` body could evaluate to."""
    match expression:
        case ast.IfExp(body=body, orelse=orelse):
            return _resolve(body, scope, view_class) + _resolve(orelse, scope, view_class)
        case ast.BoolOp(values=values):
            return [found for value in values for found in _resolve(value, scope, view_class)]
        case ast.Name(id=name):
            return [scope[name]] if name in scope else []
        case ast.Attribute():
            attributes: list[str] = []
            node: ast.expr = expression
            while isinstance(node, ast.Attribute):
                attributes.append(node.attr)
                node = node.value
            if not isinstance(node, ast.Name):
                return []
            # `self.x.y` walks the class, anything else walks an imported module.
            found = view_class if node.id == "self" else scope.get(node.id)
            for attribute in reversed(attributes):
                found = getattr(found, attribute, None)
            return [found] if found is not None else []
        case ast.Subscript(value=value):
            return [
                entry
                for mapping in _resolve(value, scope, view_class)
                if isinstance(mapping, dict)
                for entry in mapping.values()
            ]
        case ast.Call(func=ast.Attribute(value=value, attr="get"), args=args):
            # A `serializer_classes.get(self.action, default)` lookup table.
            resolved = [
                entry
                for mapping in _resolve(value, scope, view_class)
                if isinstance(mapping, dict)
                for entry in mapping.values()
            ]
            return resolved + [found for argument in args for found in _resolve(argument, scope, view_class)]
        case _:
            return []


def _function_scope(tree: ast.AST, scope: dict[str, Any], view_class: type) -> tuple[dict[str, Any], set[type]]:
    """Names bound inside the function body: deferred imports and local assignments.

    The serializers bound here are returned separately from the scope, because the
    scope also carries the defining module's globals, and every serializer that module
    happens to import is not a serializer this view can hand to a request.
    """
    scope = dict(scope)
    bound: set[type] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            try:
                module = importlib.import_module(node.module)
            except Exception:
                continue
            for alias in node.names:
                imported = getattr(module, alias.name, None)
                if imported is not None:
                    scope[alias.asname or alias.name] = imported
                    if _is_serializer(imported):
                        bound.add(imported)
    for node in ast.walk(tree):
        targets: Sequence[ast.expr]
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        assigned = [found for found in _resolve(value, scope, view_class) if _is_serializer(found)]
        bound.update(assigned)
        for target in targets:
            if isinstance(target, ast.Name) and assigned:
                scope[target.id] = assigned[0]
    return scope, bound


def _action_literals(test: ast.expr) -> set[str] | None:
    """The actions a test requires, or `None` when it constrains the action not at all.

    Only a plain `self.action == "x"` or `self.action in (...)` counts. Anything else
    reads as unconstrained, so an unrecognised guard widens the search rather than
    narrowing it.
    """
    match test:
        case ast.BoolOp(op=ast.And(), values=values):
            # Every operand must hold, so any one of them can supply the constraint.
            required = {action for value in values for action in (_action_literals(value) or set())}
            return required or None
        case ast.Compare(
            left=ast.Attribute(value=ast.Name(id="self"), attr="action"),
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=str(action))],
        ):
            return {action}
        case ast.Compare(
            left=ast.Attribute(value=ast.Name(id="self"), attr="action"),
            ops=[ast.In()],
            comparators=[ast.Tuple(elts=elements) | ast.List(elts=elements) | ast.Set(elts=elements)],
        ):
            actions = {element.value for element in elements if isinstance(element, ast.Constant)}
            return {action for action in actions if isinstance(action, str)} or None
        case _:
            return None


def _required_actions(test: ast.expr, view_class: type) -> set[str] | None:
    """The actions a branch test requires, following a `self.is_x()` guard one level.

    `InsightViewSet` gates its basic serializer on `self._is_basic_request()`, and that
    helper is where `self.action in ("list", "retrieve")` lives, so a guard that reads
    only the branch test would miss the constraint entirely.
    """
    direct = _action_literals(test)
    if direct is not None:
        return direct
    match test:
        case ast.Call(func=ast.Attribute(value=ast.Name(id="self"), attr=str(name)), args=[], keywords=[]):
            for klass in view_class.__mro__:
                helper = vars(klass).get(name)
                if helper is None:
                    continue
                try:
                    tree = ast.parse(textwrap.dedent(inspect.getsource(helper)))
                except Exception:
                    return None
                returned = [
                    node.value for node in ast.walk(tree) if isinstance(node, ast.Return) and node.value is not None
                ]
                return _action_literals(returned[0]) if len(returned) == 1 else None
    return None


def _returns_by_action(body: list[ast.stmt], view_class: type) -> list[tuple[ast.expr, set[str] | None]]:
    """Each returned expression, paired with the actions that have to hold to reach it.

    Only the taken branch of an action guard narrows. An `else` inherits the enclosing
    constraint instead of the complement, which keeps the result a superset.
    """
    found: list[tuple[ast.expr, set[str] | None]] = []

    def walk(statements: list[ast.stmt], required: set[str] | None) -> None:
        for statement in statements:
            if isinstance(statement, ast.Return):
                if statement.value is not None:
                    found.append((statement.value, required))
                continue
            if isinstance(statement, ast.If):
                actions = _required_actions(statement.test, view_class)
                narrowed = required & actions if required and actions else actions or required
                walk(statement.body, narrowed)
                walk(statement.orelse, required)
                continue
            for field in ("body", "orelse", "finalbody"):
                nested = getattr(statement, field, None)
                if isinstance(nested, list):
                    walk(nested, required)

    walk(body, None)
    return found


def _is_super_delegation(expression: ast.expr) -> bool:
    """`return super().get_serializer_class()`, which the MRO walk already covers."""
    match expression:
        case ast.Call(func=ast.Attribute(value=ast.Call(func=ast.Name(id="super")), attr="get_serializer_class")):
            return True
        case _:
            return False


def _serializer_sources(view_class: type, action: str) -> tuple[dict[str, set[type]], list[str]]:
    """Serializers this action could be handed, grouped by the mechanism that names each.

    Grouped rather than merged because `test_every_discovery_path_finds_something`
    asserts every mechanism still contributes, and a bucket that folds several together
    stays non-empty while one of them is dead.

    `get_serializer_class` is read statically rather than called, because calling it
    returns the one serializer that matches a synthesized request: a view that branches
    on a header or on request data would show the guard a single arm and hide the rest.
    """
    sources: dict[str, set[type]] = {name: set() for name in SERIALIZER_SOURCES}
    unresolved: list[str] = []
    declared = getattr(view_class, "serializer_class", None)
    if _is_serializer(declared):
        sources["serializer_class attribute"].add(declared)
    for attribute in vars(view_class).values():
        if isinstance(attribute, dict):
            sources["serializer lookup table"].update(entry for entry in attribute.values() if _is_serializer(entry))
    for klass in view_class.__mro__:
        function = vars(klass).get("get_serializer_class")
        if function is None or klass is GenericAPIView:
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        except Exception as error:
            unresolved.append(f"{klass.__qualname__}.get_serializer_class: {type(error).__name__}")
            continue
        module = sys.modules.get(function.__module__)
        module_scope = vars(module) if module is not None else {}
        scope, locally_bound = _function_scope(tree, module_scope, view_class)
        sources["get_serializer_class local"].update(locally_bound)
        for returned, required in _returns_by_action(tree.body, view_class):
            if required is not None and action not in required:
                continue
            resolved = _resolve(returned, scope, view_class)
            serializer_classes = [entry for entry in resolved if _is_serializer(entry)]
            if serializer_classes:
                sources["get_serializer_class return"].update(serializer_classes)
            elif not resolved and not _is_super_delegation(returned):
                unresolved.append(f"{klass.__qualname__}.get_serializer_class -> {ast.unparse(returned)[:60]}")
    return sources, unresolved


def _serializer_choices(view_class: type, action: str) -> tuple[set[type], list[str]]:
    """Every serializer a view could hand to this action, and what would not resolve."""
    sources, unresolved = _serializer_sources(view_class, action)
    return set().union(*sources.values()), unresolved


def _serializer_classes(declared: Any) -> set[type]:
    """The serializer classes behind a request-body declaration.

    A declaration is not always a class: `inline_serializer` returns an instance,
    `many=True` wraps the real serializer in a `ListSerializer`, a media-type
    mapping holds one declaration per content type, and a `PolymorphicProxySerializer`
    is a schema-only union whose members are the serializers that read the body.
    """
    if isinstance(declared, dict):
        return {entry for value in declared.values() for entry in _serializer_classes(value)}
    if isinstance(declared, list | tuple):
        return {entry for value in declared for entry in _serializer_classes(value)}
    if isinstance(declared, serializers.ListSerializer):
        return _serializer_classes(declared.child)
    if isinstance(declared, PolymorphicProxySerializer):
        return _serializer_classes(declared.serializers)
    if isinstance(declared, serializers.BaseSerializer):
        return {type(declared)}
    if _is_serializer(declared):
        return {declared}
    return set()


def _declared_requests(handler: Any) -> list[Any]:
    """Every `request=` value an `@extend_schema` decorator gives a handler.

    drf-spectacular does not store the declaration as data. It builds a schema class
    that closes over `request` and keeps it in the handler's `kwargs`, so the value is
    read back out of that closure. Stacked decorators chain these classes, and every
    link counts: `@validated_request` declares the serializer that validates the body,
    and an outer `@extend_schema` can replace it in the schema with a schema-only one.
    `test_request_body_declarations_stay_readable` fails if a drf-spectacular upgrade
    moves the closure, rather than letting discovery narrow quietly.
    """
    found: list[Any] = []
    handler_kwargs = getattr(handler, "kwargs", None)
    schema = handler_kwargs.get("schema") if isinstance(handler_kwargs, dict) else None
    for klass in getattr(schema, "__mro__", ()):
        getter = vars(klass).get("get_request_serializer")
        code = getattr(getter, "__code__", None)
        closure = getattr(getter, "__closure__", None) or ()
        for variable, cell in zip(getattr(code, "co_freevars", ()), closure):
            if variable == "request" and cell.cell_contents is not empty:
                found.append(cell.cell_contents)
    return found


def _request_body_serializers(view_class: type, handler_names: set[str]) -> set[type] | None:
    """Serializers an `@extend_schema(request=...)` decorator names on a write handler.

    `None` means no handler declares a body. An empty set means every declaration is
    `request=None`, so the operation takes no body.
    """
    found: set[type] | None = None
    for name in handler_names:
        for request in _declared_requests(getattr(view_class, name, None)):
            found = (found or set()) | _serializer_classes(request)
    return found


def _write_exposed_serializers() -> tuple[set[type], dict[str, str]]:
    """Every serializer reachable from a write route, and everything that would not resolve."""
    found: set[type] = set()
    unresolved: dict[str, str] = {}
    for _path, method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        if method not in WRITE_METHODS or view_class is None:
            continue
        # A viewset routes the method to an action; a plain APIView handles it by name.
        actions = getattr(callback, "actions", None) or {}
        action = actions.get(method.lower()) or method.lower()
        declared = _request_body_serializers(view_class, {method.lower(), action})
        if declared == set():
            continue
        found.update(declared or set())
        choices, problems = _serializer_choices(view_class, action)
        found.update(choices)
        if problems:
            unresolved[_dotted_name(view_class)] = "; ".join(problems)
    return found, unresolved


def _writable_timestamps(serializer_class: type[serializers.BaseSerializer]) -> dict[str, str]:
    """Each writable timestamp field on a serializer, mapped to the model behind it."""
    model = getattr(getattr(serializer_class, "Meta", None), "model", None)
    found: dict[str, str] = {}
    for name, field in serializer_class().fields.items():
        if not isinstance(field, serializers.DateTimeField) or field.read_only:
            continue
        if model is None:
            found[name] = "no model"
            continue
        try:
            model_field = model._meta.get_field(field.source or name)
        except FieldDoesNotExist:
            # A declared field backed by no column of its own: a write-only input, or
            # a dotted source into a related model. It still takes a client value on a
            # write route, so it needs a reason rather than a silent skip.
            found[name] = "no model column"
            continue
        if isinstance(model_field, models.DateTimeField):
            found[name] = model.__name__
    return found


@functools.cache
def collect_violations() -> tuple[dict[str, str], dict[str, str]]:
    """Every writable timestamp a write route exposes, and what the guard could not read.

    The first mapping is keyed by `module.Serializer.field` and holds the model behind
    the column; the second is keyed by the view or serializer that failed, and says why.
    """
    writable: dict[str, str] = {}
    serializer_classes, problems = _write_exposed_serializers()
    for serializer_class in serializer_classes:
        try:
            timestamps = _writable_timestamps(serializer_class)
        except Exception as error:
            problems[_dotted_name(serializer_class)] = f"{type(error).__name__}: {error}"
            continue
        for name, model_name in timestamps.items():
            writable[f"{_dotted_name(serializer_class)}.{name}"] = model_name
    return writable, problems


def test_every_writable_timestamp_has_been_reviewed() -> None:
    writable, _ = collect_violations()
    unreviewed = sorted(f"{key} ({model})" for key, model in writable.items() if key not in REVIEWED_WRITABLE)
    assert not unreviewed, (
        "These write routes expose a timestamp nobody has classified. If the backend owns the "
        "value, make the field read-only: put read_only=True on a declared field, which covers every "
        "field on a plain Serializer, or add a field a ModelSerializer generates to read_only_fields "
        "on Meta. If a client is supposed to set it, add it to REVIEWED_WRITABLE in "
        "posthog/test/repo_invariants/test_serializer_timestamp_guard.py with a one-line reason:\n"
        + "\n".join(unreviewed)
    )


def test_every_write_route_can_be_checked() -> None:
    _, problems = collect_violations()
    unexpected = sorted(f"{key} ({error})" for key, error in problems.items() if key not in UNCHECKED)
    assert not unexpected, (
        "The guard could not read these, so their write routes go unchecked. Make the view or "
        "serializer resolvable without a request, or add it to UNCHECKED in "
        "posthog/test/repo_invariants/test_serializer_timestamp_guard.py with a one-line reason:\n"
        + "\n".join(unexpected)
    )


def test_reviewed_entries_still_match_a_writable_field() -> None:
    # Without this, the registry drifts: an entry survives a field being made read-only,
    # renamed, or dropped. It also catches the larger failure, a change that narrows
    # discovery, because the fields that fall out of the sweep leave their entries
    # unmatched instead of passing as reviewed.
    writable, problems = collect_violations()
    stale = sorted((set(REVIEWED_WRITABLE) - set(writable)) | (set(UNCHECKED) - set(problems)))
    assert not stale, (
        "These REVIEWED_WRITABLE or UNCHECKED entries no longer match anything the guard found. "
        "Delete them if the field is now read-only or gone. If the field still exists, discovery "
        "stopped reaching it, which leaves its write route unchecked:\n" + "\n".join(stale)
    )


def test_discovery_reaches_dynamically_selected_serializers() -> None:
    discovered = {_dotted_name(serializer) for serializer in _write_exposed_serializers()[0]}
    missing = sorted(f"{name} ({why})" for name, why in HARD_TO_DISCOVER.items() if name not in discovered)
    assert not missing, (
        "Discovery no longer reaches these serializers, so a server-owned timestamp on one of them "
        "would pass the sweep above. Reading get_serializer_class statically is what finds them:\n" + "\n".join(missing)
    )


def test_every_discovery_path_finds_something() -> None:
    # A mechanism that finds nothing on every route is indistinguishable from one with
    # nothing to find, so a broken reader keeps passing the sweep above while silently
    # contributing zero. Requiring each to be non-empty across the whole repository
    # separates the two, and is what fails when a drf-spectacular upgrade moves the
    # closure the request-body reader depends on.
    found: dict[str, set[type]] = {name: set() for name in (*SERIALIZER_SOURCES, REQUEST_BODY_SOURCE)}
    for _path, method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        if method not in WRITE_METHODS or view_class is None:
            continue
        actions = getattr(callback, "actions", None) or {}
        action = actions.get(method.lower()) or method.lower()
        sources, _ = _serializer_sources(view_class, action)
        for name, serializer_classes in sources.items():
            found[name] |= serializer_classes
        found[REQUEST_BODY_SOURCE] |= _request_body_serializers(view_class, {method.lower(), action}) or set()
    silent = sorted(name for name, serializer_classes in found.items() if not serializer_classes)
    assert not silent, (
        "These discovery paths found no serializer on any write route in the repository, so "
        "they are contributing nothing to the sweep above. Either the code they read moved, or "
        "they are broken:\n" + "\n".join(silent)
    )


# Fixtures for the discovery tests below. They sit at module level because a view
# resolves a serializer name against the globals of the module that defines it, which
# is where every real serializer lives.
class ReadShapeSerializer(serializers.Serializer):
    pass


class WriteShapeSerializer(serializers.Serializer):
    pass


class BranchingViewSet(viewsets.GenericViewSet):
    def _wants_read_shape(self) -> bool:
        return self.action in ("list", "retrieve")

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self._wants_read_shape():
            return ReadShapeSerializer
        return WriteShapeSerializer


class OpaqueGuardViewSet(viewsets.GenericViewSet):
    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.request.headers.get("x-shape") == "read":
            return ReadShapeSerializer
        return WriteShapeSerializer


def _choose_serializer(action: str) -> type[serializers.Serializer]:
    return WriteShapeSerializer


class FactoryViewSet(viewsets.GenericViewSet):
    def get_serializer_class(self) -> type[serializers.Serializer]:
        return _choose_serializer(self.action)


class DelegatingViewSet(viewsets.GenericViewSet):
    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        return super().get_serializer_class()


def test_read_only_action_serializers_are_not_write_route_violations() -> None:
    # A serializer a view hands only to list or retrieve is not exposed to a write
    # request, so reporting it would send an owning team after a hole that is not there.
    # The guard follows `_wants_read_shape` to find the constraint, because a helper is
    # where InsightViewSet keeps it.
    assert _serializer_choices(BranchingViewSet, "create")[0] == {WriteShapeSerializer}
    assert _serializer_choices(BranchingViewSet, "list")[0] == {ReadShapeSerializer, WriteShapeSerializer}


def test_unrecognized_action_guard_keeps_every_serializer() -> None:
    # Narrowing on a guard the parser does not understand would drop a serializer a
    # write route can still reach, so an unreadable guard must constrain nothing.
    assert _serializer_choices(OpaqueGuardViewSet, "create")[0] == {ReadShapeSerializer, WriteShapeSerializer}


def test_unresolvable_serializer_factory_is_reported() -> None:
    # A factory call resolves to nothing, so the route would pass unchecked unless the
    # guard reports it. super().get_serializer_class() is the one call the MRO covers.
    assert _serializer_choices(FactoryViewSet, "create")[1] == [
        "FactoryViewSet.get_serializer_class -> _choose_serializer(self.action)"
    ]
    assert _serializer_choices(DelegatingViewSet, "create")[1] == []


def test_request_body_declarations_stay_readable() -> None:
    # drf-spectacular keeps `request=` in a closure rather than as data, so the reader
    # depends on its internals. An upgrade that moves it must fail here.
    class DeclaredBodySerializer(serializers.Serializer):
        pass

    @extend_schema_view(create=extend_schema(request=DeclaredBodySerializer))
    class DecoratedViewSet(viewsets.GenericViewSet):
        def create(self, request: Any) -> None: ...

    @extend_schema_view(create=extend_schema(request=None))
    class BodylessViewSet(viewsets.GenericViewSet):
        def create(self, request: Any) -> None: ...

    assert _request_body_serializers(DecoratedViewSet, {"create"}) == {DeclaredBodySerializer}
    assert _request_body_serializers(BodylessViewSet, {"create"}) == set()
    assert _request_body_serializers(OpaqueGuardViewSet, {"create"}) is None


def test_modelless_serializer_timestamps_are_reported() -> None:
    class ModellessSerializer(serializers.Serializer):
        starts_at = serializers.DateTimeField()
        created_at = serializers.DateTimeField(read_only=True)

    assert _writable_timestamps(ModellessSerializer) == {"starts_at": "no model"}


def test_request_body_declarations_normalize_to_classes() -> None:
    # inline_serializer returns an instance, many=True wraps one in a ListSerializer,
    # and a PolymorphicProxySerializer is a union read through its members.
    class BodySerializer(serializers.Serializer):
        pass

    class OtherBodySerializer(serializers.Serializer):
        pass

    assert _serializer_classes(BodySerializer(many=True)) == {BodySerializer}
    assert _serializer_classes({"application/json": BodySerializer()}) == {BodySerializer}
    union = PolymorphicProxySerializer(
        component_name="BodyUnion", serializers=[BodySerializer, OtherBodySerializer], resource_type_field_name=None
    )
    assert _serializer_classes(union) == {BodySerializer, OtherBodySerializer}
    inline = inline_serializer("InlineBody", fields={"name": serializers.CharField()})
    assert _serializer_classes(inline) == {type(inline)}
