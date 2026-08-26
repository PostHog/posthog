from posthog.temporal import ai
from posthog.temporal.ai_observability import (
    ACTIVITIES as LLM_ANALYTICS_ACTIVITIES,
    WORKFLOWS as LLM_ANALYTICS_WORKFLOWS,
)

from products.signals.backend.temporal import (
    ACTIVITIES as SIGNALS_PRODUCT_ACTIVITIES,
    WORKFLOWS as SIGNALS_PRODUCT_WORKFLOWS,
)


class TestAITemporalModuleIntegrity:
    def test_workflows_remain_unchanged(self):
        """Ensure all expected workflows are present in the module."""
        expected_workflows = [
            "SyncVectorsWorkflow",
            "AssistantConversationRunnerWorkflow",
            "ChatAgentWorkflow",
            "ResearchAgentWorkflow",
            "SummarizeLLMTracesWorkflow",
            "AnomalyInvestigationWorkflow",
            "CheckpointCompactionWorkflow",
        ]
        actual_workflow_names = [workflow.__name__ for workflow in ai.AI_WORKFLOWS]
        assert len(actual_workflow_names) == len(expected_workflows), (
            f"Workflow count mismatch. Expected {len(expected_workflows)}, got {len(actual_workflow_names)}. "
            "If you're adding/removing workflows, update this test accordingly."
        )
        for expected in expected_workflows:
            assert expected in actual_workflow_names, (
                f"Workflow '{expected}' is missing from ai.AI_WORKFLOWS. If this was intentional, update the test."
            )
        for actual in actual_workflow_names:
            assert actual in expected_workflows, (
                f"Unexpected workflow '{actual}' found in ai.AI_WORKFLOWS. If this was intentional, update the test."
            )

    def test_activities_remain_unchanged(self):
        """Ensure all expected activities are present in the module."""
        expected_activities = [
            "get_approximate_actions_count",
            "batch_summarize_actions",
            "batch_embed_and_sync_actions",
            "process_conversation_activity",
            "process_chat_agent_activity",
            "process_research_agent_activity",
            "summarize_llm_traces_activity",
            "investigate_anomaly_activity",
            "select_checkpoint_compaction_batch",
            "compact_checkpoint_conversations",
        ]
        actual_activity_names = [activity.__name__ for activity in ai.AI_ACTIVITIES]
        assert len(actual_activity_names) == len(expected_activities), (
            f"Activity count mismatch. Expected {len(expected_activities)}, got {len(actual_activity_names)}. "
            "If you're adding/removing activities, update this test accordingly."
        )
        for expected in expected_activities:
            assert expected in actual_activity_names, (
                f"Activity '{expected}' is missing from ai.AI_ACTIVITIES. If this was intentional, update the test."
            )
        for actual in actual_activity_names:
            assert actual in expected_activities, (
                f"Unexpected activity '{actual}' found in ai.AI_ACTIVITIES. If this was intentional, update the test."
            )

    def test_all_exports_remain_unchanged(self):
        """Ensure __all__ exports remain unchanged."""
        expected_exports = [
            "SyncVectorsInputs",
            "SummarizeLLMTracesInputs",
        ]
        actual_exports = ai.__all__
        assert len(actual_exports) == len(expected_exports), (
            f"Export count mismatch. Expected {len(expected_exports)}, got {len(actual_exports)}. "
            "If you're adding/removing exports, update this test accordingly."
        )
        for expected in expected_exports:
            assert expected in actual_exports, (
                f"Export '{expected}' is missing from __all__. If this was intentional, update the test."
            )
        for actual in actual_exports:
            assert actual in expected_exports, (
                f"Unexpected export '{actual}' found in __all__. If this was intentional, update the test."
            )


class TestSignalsProductModuleIntegrity:
    def test_workflows_remain_unchanged(self):
        """Ensure all expected signals product workflows are present."""
        expected_workflows = [
            "BackfillErrorTrackingWorkflow",
            "TeamSignalGroupingWorkflow",
            "TeamSignalGroupingV2Workflow",
            "BufferSignalsWorkflow",
            "SignalEmitterWorkflow",
            "SignalReportSummaryWorkflow",
            "SignalReportReingestionWorkflow",
            "TeamSignalReingestionWorkflow",
            "SignalReportDeletionWorkflow",
            "EmitEvalSignalWorkflow",
            "RunSignalsScoutWorkflow",
            "SignalsScoutCoordinatorWorkflow",
            "CustomSignalAgentWorkflow",
            "SignalReportInboxNotificationWorkflow",
        ]
        actual_workflow_names = [w.__name__ for w in SIGNALS_PRODUCT_WORKFLOWS]
        assert len(actual_workflow_names) == len(expected_workflows), (
            f"Workflow count mismatch. Expected {len(expected_workflows)}, got {len(actual_workflow_names)}. "
            "If you're adding/removing workflows, update this test accordingly."
        )
        for expected in expected_workflows:
            assert expected in actual_workflow_names, (
                f"Workflow '{expected}' is missing from SIGNALS_PRODUCT_WORKFLOWS."
            )

    def test_activities_remain_unchanged(self):
        """Ensure all expected signals product activities are present."""
        expected_activities = [
            "dispatch_inbox_slack_notifications_activity",
            "get_inbox_notification_state_activity",
            "send_report_inbox_notifications_activity",
            "emit_backfill_signal_activity",
            "fetch_error_tracking_issues_activity",
            "assign_and_emit_signal_activity",
            "capture_signal_dropped_activity",
            "check_signals_quota_limited_activity",
            "delete_report_activity",
            "emit_eval_signal_activity",
            "fetch_report_contexts_activity",
            "flush_signals_to_s3_activity",
            "signal_with_start_grouping_v2_activity",
            "submit_signal_to_buffer_activity",
            "fetch_signal_type_examples_activity",
            "fetch_signals_for_report_activity",
            "generate_search_queries_activity",
            "get_embedding_activity",
            "match_signal_to_report_activity",
            "mark_report_failed_activity",
            "read_signals_from_s3_activity",
            "check_report_quota_gate_activity",
            "mark_report_in_progress_activity",
            "mark_report_pending_input_activity",
            "mark_report_ready_activity",
            "publish_report_completed_activity",
            "report_has_assigned_signals_activity",
            "revert_report_to_candidate_activity",
            "delete_team_reports_activity",
            "get_grouping_paused_state_activity",
            "pause_grouping_until_activity",
            "process_team_signals_batch_activity",
            "reingest_signals_activity",
            "reset_report_to_potential_activity",
            "restore_grouping_pause_activity",
            "run_agentic_report_activity",
            "run_signal_semantic_search_activity",
            "report_safety_judge_activity",
            "safety_filter_activity",
            "select_repository_activity",
            "soft_delete_report_signals_activity",
            "verify_match_specificity_activity",
            "wait_for_signal_in_clickhouse_activity",
            "fetch_enabled_signals_scout_runs_activity",
            "stamp_dispatched_signals_scout_runs_activity",
            "run_signals_scout_activity",
            "run_custom_signal_agent_activity",
        ]
        actual_activity_names = [a.__name__ for a in SIGNALS_PRODUCT_ACTIVITIES]
        assert len(actual_activity_names) == len(expected_activities), (
            f"Activity count mismatch. Expected {len(expected_activities)}, got {len(actual_activity_names)}. "
            "If you're adding/removing activities, update this test accordingly."
        )
        for expected in expected_activities:
            assert expected in actual_activity_names, (
                f"Activity '{expected}' is missing from SIGNALS_PRODUCT_ACTIVITIES."
            )


class TestAIObservabilityModuleIntegrity:
    def test_workflows_remain_unchanged(self):
        """Ensure all expected LLMA-worker workflows are present."""
        expected_workflows = [
            "BatchTraceSummarizationWorkflow",
            "BatchTraceSummarizationCoordinatorWorkflow",
            "DailyTraceClusteringWorkflow",
            "TraceClusteringCoordinatorWorkflow",
            "ScheduleAllEvalReportsWorkflow",
            "CheckCountTriggeredReportsWorkflow",
            "GenerateAndDeliverEvalReportWorkflow",
            "EmitEvalReportSignalWorkflow",
            "AIObservabilityEvaluationSamplerCoordinatorWorkflow",
            "AIObservabilityEvaluationSamplerWorkflow",
            "AIObservabilityEvaluationClusteringCoordinatorWorkflow",
            "AIObservabilityEvaluationClusteringWorkflow",
            "RunEvaluationWorkflow",
        ]
        actual_workflow_names = [w.__name__ for w in LLM_ANALYTICS_WORKFLOWS]
        assert len(actual_workflow_names) == len(expected_workflows), (
            f"Workflow count mismatch. Expected {len(expected_workflows)}, got {len(actual_workflow_names)}. "
            "If you're adding/removing workflows, update this test accordingly."
        )
        for expected in expected_workflows:
            assert expected in actual_workflow_names, f"Workflow '{expected}' is missing from LLM_ANALYTICS_WORKFLOWS."

    def test_activities_remain_unchanged(self):
        """Ensure all expected LLMA-worker activities are present."""
        expected_activities = [
            "get_team_ids_for_ai_observability",
            "sample_items_in_window_activity",
            "fetch_and_format_activity",
            "summarize_and_save_activity",
            "fetch_all_clustering_filters_activity",
            "fetch_all_clustering_jobs_activity",
            "perform_clustering_compute_activity",
            "generate_cluster_labels_activity",
            "compute_cluster_aggregates_activity",
            "emit_cluster_events_activity",
            "fetch_due_eval_reports_activity",
            "fetch_count_triggered_eval_report_candidates_activity",
            "check_count_triggered_eval_report_activity",
            "check_count_triggered_eval_reports_activity",
            "prepare_report_context_activity",
            "run_eval_report_agent_activity",
            "store_report_run_activity",
            "deliver_report_activity",
            "update_next_delivery_date_activity",
            "emit_eval_report_signal_activity",
            "sample_and_embed_for_job_activity",
            "perform_evaluation_clustering_compute_activity",
            "fetch_evaluation_metadata_activity",
            "generate_evaluation_cluster_labels_activity",
            "compute_evaluation_cluster_aggregates_activity",
            "emit_evaluation_cluster_events_activity",
            "fetch_evaluation_activity",
            "disable_evaluation_activity",
            "send_evaluation_disabled_email_activity",
            "update_key_state_activity",
            "execute_llm_judge_activity",
            "execute_hog_eval_activity",
            "execute_sentiment_eval_activity",
            "emit_evaluation_event_activity",
            "emit_internal_telemetry_activity",
            "emit_eval_signal_activity",
        ]
        actual_activity_names = [a.__name__ for a in LLM_ANALYTICS_ACTIVITIES]
        assert len(actual_activity_names) == len(expected_activities), (
            f"Activity count mismatch. Expected {len(expected_activities)}, got {len(actual_activity_names)}. "
            "If you're adding/removing activities, update this test accordingly."
        )
        for expected in expected_activities:
            assert expected in actual_activity_names, f"Activity '{expected}' is missing from LLM_ANALYTICS_ACTIVITIES."
