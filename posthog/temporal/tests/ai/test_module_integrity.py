from posthog.temporal import ai
from posthog.temporal.ai.video_segment_clustering import (
    VIDEO_SEGMENT_CLUSTERING_ACTIVITIES,
    VIDEO_SEGMENT_CLUSTERING_WORKFLOWS,
)
from posthog.temporal.session_replay import session_summary

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
            "SlackConversationRunnerWorkflow",
            "PostHogCodeSlackMentionWorkflow",
            "PostHogCodeSlackTerminateTaskWorkflow",
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
            "process_slack_conversation_activity",
            "resolve_posthog_code_slack_user_activity",
            "handle_posthog_code_rules_command_activity",
            "collect_posthog_code_thread_messages_activity",
            "create_posthog_code_routing_rule_activity",
            "select_posthog_code_repository_activity",
            "classify_posthog_code_task_needs_repo_activity",
            "post_posthog_code_no_repos_activity",
            "post_posthog_code_repo_picker_activity",
            "create_posthog_code_task_for_repo_activity",
            "forward_posthog_code_followup_activity",
            "post_posthog_code_picker_timeout_activity",
            "post_posthog_code_internal_error_activity",
            "process_posthog_code_terminate_task_activity",
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
            "SlackConversationRunnerWorkflowInputs",
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


class TestSessionSummaryTemporalModuleIntegrity:
    def test_session_summary_workflows(self):
        """Ensure all expected session summary workflows are present."""
        expected_workflows = [
            "SummarizeSingleSessionStreamWorkflow",
            "SummarizeSingleSessionWorkflow",
            "SummarizeSessionGroupWorkflow",
        ]
        actual_workflow_names = [w.__name__ for w in session_summary.SESSION_SUMMARY_WORKFLOWS]
        assert len(actual_workflow_names) == len(expected_workflows), (
            f"Workflow count mismatch. Expected {len(expected_workflows)}, got {len(actual_workflow_names)}. "
            "If you're adding/removing workflows, update this test accordingly."
        )
        for expected in expected_workflows:
            assert expected in actual_workflow_names, (
                f"Workflow '{expected}' is missing from SESSION_SUMMARY_WORKFLOWS."
            )

    def test_session_summary_activities(self):
        """Ensure all expected session summary activities are present."""
        expected_activities = [
            "stream_llm_single_session_summary_activity",
            "get_llm_single_session_summary_activity",
            "fetch_session_batch_events_activity",
            "extract_session_group_patterns_activity",
            "assign_events_to_patterns_activity",
            "fetch_session_data_activity",
            "combine_patterns_from_chunks_activity",
            "split_session_summaries_into_chunks_for_patterns_extraction_activity",
            "validate_llm_single_session_summary_with_videos_activity",
            "prep_session_video_asset_activity",
            "upload_video_to_gemini_activity",
            "analyze_video_segment_activity",
            "embed_and_store_segments_activity",
            "emit_session_problem_signals_activity",
            "store_video_session_summary_activity",
            "tag_and_highlight_session_activity",
            "cleanup_gemini_file_activity",
            "consolidate_video_segments_activity",
            "capture_timing_activity",
        ]
        actual_activity_names = [a.__name__ for a in session_summary.SESSION_SUMMARY_ACTIVITIES]
        assert len(actual_activity_names) == len(expected_activities), (
            f"Activity count mismatch. Expected {len(expected_activities)}, got {len(actual_activity_names)}. "
            "If you're adding/removing activities, update this test accordingly."
        )
        for expected in expected_activities:
            assert expected in actual_activity_names, (
                f"Activity '{expected}' is missing from SESSION_SUMMARY_ACTIVITIES."
            )


class TestVideoSegmentClusteringModuleIntegrity:
    def test_workflows_remain_unchanged(self):
        """Ensure all expected video segment clustering workflows are present."""
        expected_workflows = [
            "VideoSegmentClusteringWorkflow",
            "VideoSegmentClusteringCoordinatorWorkflow",
        ]
        actual_workflow_names = [w.__name__ for w in VIDEO_SEGMENT_CLUSTERING_WORKFLOWS]
        assert len(actual_workflow_names) == len(expected_workflows), (
            f"Workflow count mismatch. Expected {len(expected_workflows)}, got {len(actual_workflow_names)}. "
            "If you're adding/removing workflows, update this test accordingly."
        )
        for expected in expected_workflows:
            assert expected in actual_workflow_names, (
                f"Workflow '{expected}' is missing from VIDEO_SEGMENT_CLUSTERING_WORKFLOWS."
            )

    def test_activities_remain_unchanged(self):
        """Ensure all expected video segment clustering activities are present."""
        expected_activities = [
            "get_sessions_to_prime_activity",
            "list_teams_with_session_analysis_signals_activity",
        ]
        actual_activity_names = [a.__name__ for a in VIDEO_SEGMENT_CLUSTERING_ACTIVITIES]
        assert len(actual_activity_names) == len(expected_activities), (
            f"Activity count mismatch. Expected {len(expected_activities)}, got {len(actual_activity_names)}. "
            "If you're adding/removing activities, update this test accordingly."
        )
        for expected in expected_activities:
            assert expected in actual_activity_names, (
                f"Activity '{expected}' is missing from VIDEO_SEGMENT_CLUSTERING_ACTIVITIES."
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
            "emit_backfill_signal_activity",
            "fetch_error_tracking_issues_activity",
            "assign_and_emit_signal_activity",
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
            "mark_report_in_progress_activity",
            "mark_report_pending_input_activity",
            "mark_report_ready_activity",
            "publish_report_completed_activity",
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
