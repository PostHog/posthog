from collections.abc import Iterator

from django.urls import URLPattern, URLResolver, get_resolver

from rest_framework.generics import GenericAPIView
from rest_framework.mixins import ListModelMixin
from rest_framework.pagination import CursorPagination
from rest_framework.viewsets import ViewSetMixin

from posthog.api.routing import TeamAndOrgViewSetMixin

LIST_VIEWSETS_WITHOUT_DIRECT_SHARED_PAGINATION = {
    "posthog.api.async_migration.AsyncMigrationsViewset",
    "posthog.api.authentication.DevLoginViewSet",
    "posthog.api.dead_letter_queue.DeadLetterQueueViewSet",
    "posthog.api.instance_settings.InstanceSettingsViewset",
    "posthog.api.personal_api_key.PersonalAPIKeyViewSet",
    "posthog.api.user.UserViewSet",
    "posthog.api.user_integration.UserIntegrationViewSet",
    "products.cdp.backend.api.hog_function_template.PublicHogFunctionTemplateViewSet",
    "products.conversations.backend.api.tickets.TicketViewSet",
    "products.customer_analytics.backend.presentation.views.views.AccountViewSet",
    "products.dashboards.backend.api.dashboard.LegacyInsightViewSet",
    "products.managed_migrations.backend.api.support_batch_imports.BatchImportSupportViewSet",
    "products.product_analytics.backend.presentation.insight_ee.EnterpriseInsightsViewSet",
    "products.reminders.backend.api.reminder.ReminderViewSet",
    "products.workflows.backend.api.hog_flow.HogFlowViewSet",
    "products.workflows.backend.api.hog_flow_template.PublicHogFlowTemplateViewSet",
}

EXISTING_CUSTOM_LIST_VIEWSETS = {
    "ee.api.billing.BillingViewset",
    "ee.api.quota_limits.QuotaLimitsViewSet",
    "ee.api.subscription.SubscriptionDeliveryViewSet",
    "ee.api.subscription.SubscriptionViewSet",
    "ee.clickhouse.views.experiment_saved_metrics.ExperimentSavedMetricViewSet",
    "ee.clickhouse.views.groups.GroupsTypesViewSet",
    "ee.clickhouse.views.groups.GroupsViewSet",
    "ee.clickhouse.views.person.EnterprisePersonViewSet",
    "ee.clickhouse.views.person.LegacyEnterprisePersonViewSet",
    "posthog.admin.admins.radar_bypass_admin.RadarBypassViewSet",
    "posthog.api.advanced_activity_logs.viewset.ActivityLogViewSet",
    "posthog.api.advanced_activity_logs.viewset.AdvancedActivityLogsViewSet",
    "posthog.api.advanced_activity_logs.viewset.OrganizationAdvancedActivityLogsViewSet",
    "posthog.api.authentication.DevLoginViewSet",
    "posthog.api.cohort.CohortViewSet",
    "posthog.api.cohort.LegacyCohortViewSet",
    "posthog.api.column_configuration.ColumnConfigurationViewSet",
    "posthog.api.comments.CommentViewSet",
    "posthog.api.data_color_theme.DataColorThemeViewSet",
    "posthog.api.data_deletion_request.DataDeletionRequestViewSet",
    "posthog.api.debug_ch_queries.DebugCHQueries",
    "posthog.api.event.EventViewSet",
    "posthog.api.event.LegacyEventViewSet",
    "posthog.api.event_definition.EventDefinitionViewSet",
    "posthog.api.event_filter_config.EventFilterConfigViewSet",
    "posthog.api.file_system.file_system.FileSystemViewSet",
    "posthog.api.health_issue.HealthIssueViewSet",
    "posthog.api.ingestion_warnings.IngestionWarningsViewSet",
    "posthog.api.ingestion_warnings_v2.IngestionWarningsV2ViewSet",
    "posthog.api.instance_status.InstanceStatusViewSet",
    "posthog.api.integration.IntegrationViewSet",
    "posthog.api.llm_prompt.LLMPromptViewSet",
    "posthog.api.my_notifications.MyNotificationsViewSet",
    "posthog.api.oauth.connected_apps.ConnectedAppsViewSet",
    "posthog.api.organization_member.OrganizationMemberViewSet",
    "posthog.api.organization_notification_locks.OrganizationNotificationLockViewSet",
    "posthog.api.personal_api_key.PersonalAPIKeyViewSet",
    "posthog.api.project.ProjectViewSet",
    "posthog.api.project.RootProjectViewSet",
    "posthog.api.proxy_record.ProxyRecordViewset",
    "posthog.api.search.SearchViewSet",
    "posthog.api.sharing.SharingConfigurationViewSet",
    "posthog.api.tagged_item.TaggedItemViewSet",
    "posthog.api.uploaded_media.MediaViewSet",
    "posthog.api.user_integration.UserIntegrationViewSet",
    "posthog.api.web_vitals.WebVitalsViewSet",
    "posthog.api.webauthn.WebAuthnCredentialViewSet",
    "posthog.session_recordings.session_recording_api.SessionRecordingViewSet",
    "posthog.session_recordings.session_recording_playlist_api.SessionRecordingPlaylistViewSet",
    "posthog.taxonomy.property_definition_api.PropertyDefinitionViewSet",
    "products.access_control.backend.presentation.views.PropertyAccessControlViewSet",
    "products.actions.backend.api.action.ActionViewSet",
    "products.ai_observability.backend.api.clustering_config.ClusteringConfigViewSet",
    "products.ai_observability.backend.api.clustering_job.ClusteringJobViewSet",
    "products.ai_observability.backend.api.datasets.DatasetItemViewSet",
    "products.ai_observability.backend.api.datasets.DatasetViewSet",
    "products.ai_observability.backend.api.evaluation_backfills.EvaluationBackfillViewSet",
    "products.ai_observability.backend.api.evaluation_config.EvaluationConfigViewSet",
    "products.ai_observability.backend.api.evaluation_reports.EvaluationReportViewSet",
    "products.ai_observability.backend.api.evaluations.EvaluationViewSet",
    "products.ai_observability.backend.api.instrumentation_checklist.AIObservabilityInstrumentationChecklistViewSet",
    "products.ai_observability.backend.api.models.LLMModelsViewSet",
    "products.ai_observability.backend.api.offline_experiments.OfflineExperimentViewSet",
    "products.ai_observability.backend.api.personal_spend.PersonalSpendViewSet",
    "products.ai_observability.backend.api.provider_keys.LLMProviderKeyViewSet",
    "products.ai_observability.backend.api.review_queues.ReviewQueueItemViewSet",
    "products.ai_observability.backend.api.review_queues.ReviewQueueViewSet",
    "products.ai_observability.backend.api.score_definitions.ScoreDefinitionViewSet",
    "products.ai_observability.backend.api.taggers.TaggerViewSet",
    "products.ai_observability.backend.api.trace_reviews.TraceReviewViewSet",
    "products.alerts.backend.presentation.views.alert.AlertViewSet",
    "products.autoresearch.backend.presentation.views.views.AutoresearchModelViewSet",
    "products.autoresearch.backend.presentation.views.views.AutoresearchPipelineViewSet",
    "products.autoresearch.backend.presentation.views.views.AutoresearchRunViewSet",
    "products.autoresearch.backend.presentation.views.views.AutoresearchSuggestionViewSet",
    "products.autoresearch.backend.presentation.views.views.AutoresearchTrainingRunViewSet",
    "products.batch_exports.backend.api.batch_export.BatchExportRunViewSet",
    "products.business_knowledge.backend.api.playground.BusinessKnowledgePlaygroundChatViewSet",
    "products.business_knowledge.backend.api.views.KnowledgeGapSuggestionViewSet",
    "products.business_knowledge.backend.api.views.KnowledgeSourceViewSet",
    "products.canvas.backend.presentation.views.CanvasViewSet",
    "products.cdp.backend.api.hog_function.HogFunctionViewSet",
    "products.cdp.backend.api.hog_function_template.PublicHogFunctionTemplateViewSet",
    "products.cdp.backend.api.plugin_log_entry.PluginLogEntryViewSet",
    "products.cohorts.backend.api.staff_tools.CohortsStaffToolsViewSet",
    "products.conversations.backend.api.ai_context.AIContextAccountPropertiesViewSet",
    "products.conversations.backend.api.ai_reply_playbook.AIReplyPlaybookViewSet",
    "products.conversations.backend.api.tickets.TicketViewSet",
    "products.customer_analytics.backend.presentation.views.announcements.AnnouncementViewSet",
    "products.customer_analytics.backend.presentation.views.customer_tasks.CustomerTaskViewSet",
    "products.customer_analytics.backend.presentation.views.views.AccountNotebookViewSet",
    "products.customer_analytics.backend.presentation.views.views.AccountNotesViewSet",
    "products.customer_analytics.backend.presentation.views.views.AccountRelationshipDefinitionViewSet",
    "products.customer_analytics.backend.presentation.views.views.AccountRelationshipViewSet",
    "products.customer_analytics.backend.presentation.views.views.AccountTrackRuleViewSet",
    "products.customer_analytics.backend.presentation.views.views.AccountViewSet",
    "products.customer_analytics.backend.presentation.views.views.CalendarSyncViewSet",
    "products.customer_analytics.backend.presentation.views.views.CustomPropertyDefinitionViewSet",
    "products.customer_analytics.backend.presentation.views.views.CustomPropertySourceViewSet",
    "products.customer_analytics.backend.presentation.views.views.CustomPropertyValueViewSet",
    "products.customer_analytics.backend.presentation.views.views.CustomerJourneyViewSet",
    "products.customer_analytics.backend.presentation.views.views.CustomerProfileConfigViewSet",
    "products.customer_analytics.backend.presentation.views.views.EventStreamViewSet",
    "products.customer_analytics.backend.presentation.views.views.FeatureRequestProductAreaViewSet",
    "products.customer_analytics.backend.presentation.views.views.FeatureRequestViewSet",
    "products.dashboards.backend.api.dashboard.DashboardsViewSet",
    "products.dashboards.backend.api.dashboard.LegacyDashboardsViewSet",
    "products.dashboards.backend.api.dashboard.LegacyInsightViewSet",
    "products.dashboards.backend.api.dashboard_templates.DashboardTemplateViewSet",
    "products.data_catalog.backend.presentation.views.MetricViewSet",
    "products.data_catalog.backend.presentation.views.RelationshipProposalViewSet",
    "products.data_modeling.backend.presentation.views.edge.EdgeViewSet",
    "products.data_modeling.backend.presentation.views.node.NodeViewSet",
    "products.data_quality.backend.presentation.views.DataQualityCheckViewSet",
    "products.data_quality.backend.presentation.views.DataQualityRunViewSet",
    "products.data_warehouse.backend.presentation.views.column_annotation.WarehouseColumnAnnotationViewSet",
    "products.data_warehouse.backend.presentation.views.expression.DataWarehouseExpressionViewSet",
    "products.data_warehouse.backend.presentation.views.fix_hogql.FixHogQLViewSet",
    "products.data_warehouse.backend.presentation.views.saved_query.viewset.DataWarehouseSavedQueryViewSet",
    "products.data_warehouse.backend.presentation.views.saved_query_column_annotation.DataWarehouseSavedQueryColumnAnnotationViewSet",
    "products.data_warehouse.backend.presentation.views.view_link.ViewLinkViewSet",
    "products.endpoints.backend.presentation.views.api.EndpointViewSet",
    "products.error_tracking.backend.presentation.views.alerts.ErrorTrackingAlertViewSet",
    "products.error_tracking.backend.presentation.views.assignment_rules.ErrorTrackingAssignmentRuleViewSet",
    "products.error_tracking.backend.presentation.views.bypass_rules.ErrorTrackingBypassRuleViewSet",
    "products.error_tracking.backend.presentation.views.external_references.ErrorTrackingExternalReferenceViewSet",
    "products.error_tracking.backend.presentation.views.fingerprints.ErrorTrackingFingerprintViewSet",
    "products.error_tracking.backend.presentation.views.grouping_rules.ErrorTrackingGroupingRuleViewSet",
    "products.error_tracking.backend.presentation.views.issues.ErrorTrackingIssueViewSet",
    "products.error_tracking.backend.presentation.views.recommendations.ErrorTrackingRecommendationViewSet",
    "products.error_tracking.backend.presentation.views.releases.ErrorTrackingReleaseViewSet",
    "products.error_tracking.backend.presentation.views.severity_rules.ErrorTrackingSeverityRuleViewSet",
    "products.error_tracking.backend.presentation.views.spike_detection_config.ErrorTrackingSpikeDetectionConfigViewSet",
    "products.error_tracking.backend.presentation.views.spike_events.ErrorTrackingSpikeEventViewSet",
    "products.error_tracking.backend.presentation.views.stack_frames.ErrorTrackingStackFrameViewSet",
    "products.error_tracking.backend.presentation.views.suppression_rules.ErrorTrackingSuppressionRuleViewSet",
    "products.error_tracking.backend.presentation.views.symbol_sets.ErrorTrackingSymbolSetViewSet",
    "products.experiments.backend.presentation.views.EnterpriseExperimentsViewSet",
    "products.feature_flags.backend.api.feature_flag.FeatureFlagViewSet",
    "products.feature_flags.backend.api.feature_flag.LegacyFeatureFlagViewSet",
    "products.feature_flags.backend.api.scheduled_change.ScheduledChangeViewSet",
    "products.feature_flags.backend.api.staff_cache.FeatureFlagsStaffCacheViewSet",
    "products.feature_flags.backend.api.staff_team_config.FeatureFlagsStaffTeamConfigViewSet",
    "products.feature_flags.backend.api.staff_teams.FeatureFlagsStaffTeamSearchViewSet",
    "products.feature_flags.backend.presentation.request_usage.FeatureFlagRequestUsageViewSet",
    "products.field_notes.backend.api.FieldNoteViewSet",
    "products.growth.backend.api.identity_matching.IdentityMatchingLinkViewSet",
    "products.legal_documents.backend.presentation.views.LegalDocumentViewSet",
    "products.logs.backend.presentation.views.alerts_api.LogsAlertViewSet",
    "products.managed_migrations.backend.api.batch_imports.BatchImportViewSet",
    "products.managed_migrations.backend.api.support_batch_imports.BatchImportSupportViewSet",
    "products.mcp_analytics.backend.presentation.views.MCPFeedbackViewSet",
    "products.mcp_analytics.backend.presentation.views.MCPIntentClusterViewSet",
    "products.mcp_analytics.backend.presentation.views.MCPMissingCapabilityViewSet",
    "products.mcp_analytics.backend.presentation.views.MCPSessionViewSet",
    "products.mcp_registry.backend.presentation.views.MCPRegistryServerViewSet",
    "products.mcp_store.backend.presentation.agent_views.MCPGatewayAgentViewSet",
    "products.mcp_store.backend.presentation.gateway_views.MCPAuditEventViewSet",
    "products.mcp_store.backend.presentation.gateway_views.MCPGatewayConfigViewSet",
    "products.mcp_store.backend.presentation.gateway_views.MCPGatewayMemberViewSet",
    "products.mcp_store.backend.presentation.views.MCPOAuthRedirectViewSet",
    "products.mcp_store.backend.presentation.views.MCPServerViewSet",
    "products.notebooks.backend.presentation.views.notebook.NotebookViewSet",
    "products.notebooks.backend.presentation.views.reusable_widget.ReusableWidgetViewSet",
    "products.notifications.backend.presentation.views.NotificationsViewSet",
    "products.product_analytics.backend.presentation.events_retention.EventsRetentionViewSet",
    "products.product_analytics.backend.presentation.insight_ee.EnterpriseInsightsViewSet",
    "products.product_tours.backend.api.product_tour.ProductTourViewSet",
    "products.replay_vision.backend.api.observations.ReplayObservationViewSet",
    "products.replay_vision.backend.api.observations.SessionReplayObservationViewSet",
    "products.replay_vision.backend.api.quota.VisionQuotaViewSet",
    "products.replay_vision.backend.api.scanners.ReplayScannerViewSet",
    "products.replay_vision.backend.api.scout_reports.ScannerScoutReportViewSet",
    "products.replay_vision.backend.api.vision_alerts.VisionAlertViewSet",
    "products.review_hog.backend.api.blind_spots.ReviewBlindSpotsConfigViewSet",
    "products.review_hog.backend.api.perspectives.ReviewPerspectiveConfigViewSet",
    "products.review_hog.backend.api.resolution.ReviewResolutionConfigViewSet",
    "products.review_hog.backend.api.reviews.ReviewRecentReviewsViewSet",
    "products.review_hog.backend.api.validators.ReviewValidatorConfigViewSet",
    "products.signals.backend.scout_harness.views.SignalScoutConfigViewSet",
    "products.signals.backend.scout_harness.views.SignalScoutMembersViewSet",
    "products.signals.backend.scout_harness.views.SignalScoutNoteViewSet",
    "products.signals.backend.scout_harness.views.SignalScoutRunViewSet",
    "products.signals.backend.scout_harness.views.SignalScratchpadViewSet",
    "products.signals.backend.scout_suggestions_api.SignalScoutSuggestionViewSet",
    "products.signals.backend.views.SignalProcessingViewSet",
    "products.signals.backend.views.SignalReportArtefactViewSet",
    "products.signals.backend.views.SignalReportCheckViewSet",
    "products.signals.backend.views.SignalReportViewSet",
    "products.signals.backend.views.SignalSourceConfigViewSet",
    "products.signals.backend.views.SignalTeamConfigViewSet",
    "products.skills.backend.api.community_skills.CommunitySkillViewSet",
    "products.skills.backend.api.skills.LLMSkillViewSet",
    "products.stamphog.backend.presentation.views.DigestRunViewSet",
    "products.stamphog.backend.presentation.views.PullRequestViewSet",
    "products.stamphog.backend.presentation.views.ReviewRunViewSet",
    "products.stamphog.backend.presentation.views.StamphogRepoConfigViewSet",
    "products.streamlit_apps.backend.presentation.views.StreamlitAppViewSet",
    "products.surveys.backend.api.survey.SurveyViewSet",
    "products.tasks.backend.presentation.views.api.SandboxCustomImageViewSet",
    "products.tasks.backend.presentation.views.api.SandboxEnvironmentViewSet",
    "products.tasks.backend.presentation.views.api.TaskRunLivingArtifactViewSet",
    "products.tasks.backend.presentation.views.api.TaskRunViewSet",
    "products.tasks.backend.presentation.views.api.TaskViewSet",
    "products.tasks.backend.presentation.views.channels_api.ChannelFeedMessageViewSet",
    "products.tasks.backend.presentation.views.channels_api.ChannelViewSet",
    "products.tasks.backend.presentation.views.channels_api.TaskActivityViewSet",
    "products.tasks.backend.presentation.views.channels_api.TaskMentionViewSet",
    "products.tasks.backend.presentation.views.channels_api.TaskThreadMessageViewSet",
    "products.tasks.backend.presentation.views.config_api.TasksTeamConfigViewSet",
    "products.tasks.backend.presentation.views.config_api.TasksUserConfigViewSet",
    "products.tasks.backend.presentation.views.desktop.DesktopBetaTermsViewSet",
    "products.tasks.backend.presentation.views.loops.LoopViewSet",
    "products.tasks.backend.presentation.views.sandbox_pricing_api.SandboxComputePricingViewSet",
    "products.visual_review.backend.presentation.views.RepoRunsViewSet",
    "products.visual_review.backend.presentation.views.RepoViewSet",
    "products.visual_review.backend.presentation.views.RunViewSet",
    "products.warehouse_sources.backend.presentation.views.column_statistics.WarehouseColumnStatisticsViewSet",
    "products.warehouse_sources.backend.presentation.views.public_source_configs.PublicSourceConfigViewSet",
    "products.web_analytics.backend.api.custom_bot_rules.CustomBotRuleViewSet",
    "products.web_analytics.backend.api.heatmaps_api.HeatmapViewSet",
    "products.web_analytics.backend.api.heatmaps_api.LegacyHeatmapViewSet",
    "products.web_analytics.backend.api.heatmaps_api.SavedHeatmapViewSet",
    "products.web_analytics.backend.presentation.views.content_autopilot.ContentAutopilotProposalViewSet",
    "products.web_analytics.backend.presentation.views.content_autopilot.ContentAutopilotRunViewSet",
    "products.wizard.backend.presentation.artifacts.views.WizardRunArtifactViewSet",
    "products.wizard.backend.presentation.registry.views.WizardRegistryViewSet",
    "products.wizard.backend.presentation.runs.views.WizardRunViewSet",
    "products.wizard.backend.presentation.sessions.views.WizardSessionViewSet",
    "products.workflows.backend.api.hog_flow.HogFlowViewSet",
    "products.workflows.backend.api.hog_flow_template.HogFlowTemplateViewSet",
    "products.workflows.backend.api.hog_flow_template.PublicHogFlowTemplateViewSet",
}


def _url_patterns(patterns: list[URLPattern | URLResolver]) -> Iterator[URLPattern]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _url_patterns(pattern.url_patterns)
        else:
            yield pattern


def test_new_list_viewsets_review_their_pagination_contract() -> None:
    list_viewsets: set[str] = set()
    custom_list_viewsets: set[str] = set()
    for pattern in _url_patterns(get_resolver().url_patterns):
        viewset = getattr(pattern.callback, "cls", None)
        actions = getattr(pattern.callback, "actions", None) or {}
        if viewset is None or not issubclass(viewset, ViewSetMixin) or "list" not in actions.values():
            continue
        viewset_name = f"{viewset.__module__}.{viewset.__qualname__}"
        if viewset.list is not ListModelMixin.list:
            custom_list_viewsets.add(viewset_name)
        if not issubclass(viewset, GenericAPIView):
            continue
        pagination_class = getattr(pattern.callback, "initkwargs", {}).get("pagination_class", viewset.pagination_class)
        if pagination_class is None or issubclass(pagination_class, CursorPagination):
            continue
        if (
            issubclass(viewset, TeamAndOrgViewSetMixin)
            and viewset.paginate_queryset is TeamAndOrgViewSetMixin.paginate_queryset
        ):
            continue
        list_viewsets.add(viewset_name)

    unreviewed = sorted(list_viewsets - LIST_VIEWSETS_WITHOUT_DIRECT_SHARED_PAGINATION)
    assert not unreviewed, (
        "New standard list viewsets need a stable ordering and a page-boundary test, or a reviewed exception:\n  "
        + "\n  ".join(unreviewed)
    )

    stale = sorted(LIST_VIEWSETS_WITHOUT_DIRECT_SHARED_PAGINATION - list_viewsets)
    assert not stale, "Remove standard list viewsets that no longer bypass shared pagination:\n  " + "\n  ".join(stale)

    unreviewed_custom = sorted(custom_list_viewsets - EXISTING_CUSTOM_LIST_VIEWSETS)
    assert not unreviewed_custom, (
        "New custom list actions need a pagination review and a page-boundary test, or a reviewed exception:\n  "
        + "\n  ".join(unreviewed_custom)
    )

    stale_custom = sorted(EXISTING_CUSTOM_LIST_VIEWSETS - custom_list_viewsets)
    assert not stale_custom, "Remove custom list actions that no longer exist:\n  " + "\n  ".join(stale_custom)
