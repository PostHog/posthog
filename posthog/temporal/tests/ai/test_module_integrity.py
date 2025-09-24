from posthog.temporal import ai


class TestAITemporalModuleIntegrity:
    def test_workflows_remain_unchanged(self):
        """Ensure all expected workflows are present in the module."""
        expected_workflows = [
            "SyncVectorsWorkflow",
            "SummarizeSingleSessionStreamWorkflow",
            "SummarizeSingleSessionWorkflow",
            "SummarizeSessionGroupWorkflow",
            "AssistantConversationRunnerWorkflow",
        ]
        actual_workflow_names = [workflow.__name__ for workflow in ai.WORKFLOWS]
        assert len(actual_workflow_names) == len(expected_workflows), (
            f"Workflow count mismatch. Expected {len(expected_workflows)}, got {len(actual_workflow_names)}. "
            "If you're adding/removing workflows, update this test accordingly."
        )
        for expected in expected_workflows:
            assert expected in actual_workflow_names, (
                f"Workflow '{expected}' is missing from ai.WORKFLOWS. " "If this was intentional, update the test."
            )
        # Check for unexpected workflows
        for actual in actual_workflow_names:
            assert actual in expected_workflows, (
                f"Unexpected workflow '{actual}' found in ai.WORKFLOWS. " "If this was intentional, update the test."
            )

    def test_activities_remain_unchanged(self):
        """Ensure all expected activities are present in the module."""
        expected_activities = [
            "get_approximate_actions_count",
            "batch_summarize_actions",
            "batch_embed_and_sync_actions",
            "stream_llm_single_session_summary_activity",
            "get_llm_single_session_summary_activity",
            "fetch_session_batch_events_activity",
            "extract_session_group_patterns_activity",
            "assign_events_to_patterns_activity",
            "fetch_session_data_activity",
            "combine_patterns_from_chunks_activity",
            "split_session_summaries_into_chunks_for_patterns_extraction_activity",
            "process_conversation_activity",
            "validate_llm_single_session_summary_with_videos_activity",
        ]
        actual_activity_names = [activity.__name__ for activity in ai.ACTIVITIES]
        assert len(actual_activity_names) == len(expected_activities), (
            f"Activity count mismatch. Expected {len(expected_activities)}, got {len(actual_activity_names)}. "
            "If you're adding/removing activities, update this test accordingly."
        )
        for expected in expected_activities:
            assert expected in actual_activity_names, (
                f"Activity '{expected}' is missing from ai.ACTIVITIES. " "If this was intentional, update the test."
            )
        # Check for unexpected activities
        for actual in actual_activity_names:
            assert actual in expected_activities, (
                f"Unexpected activity '{actual}' found in ai.ACTIVITIES. " "If this was intentional, update the test."
            )

    def test_all_exports_remain_unchanged(self):
        """Ensure __all__ exports remain unchanged."""
        expected_exports = [
            "SyncVectorsInputs",
            "SingleSessionSummaryInputs",
            "SessionGroupSummaryInputs",
            "SessionGroupSummaryOfSummariesInputs",
        ]
        actual_exports = ai.__all__
        assert len(actual_exports) == len(expected_exports), (
            f"Export count mismatch. Expected {len(expected_exports)}, got {len(actual_exports)}. "
            "If you're adding/removing exports, update this test accordingly."
        )
        for expected in expected_exports:
            assert expected in actual_exports, (
                f"Export '{expected}' is missing from __all__. " "If this was intentional, update the test."
            )
        # Check for unexpected exports
        for actual in actual_exports:
            assert actual in expected_exports, (
                f"Unexpected export '{actual}' found in __all__. " "If this was intentional, update the test."
            )
