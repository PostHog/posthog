import os

import pytest
from django.test import override_settings
from flaky import flaky
from langchain_core.runnables import RunnableConfig

from ee.models.assistant import Conversation
from posthog.demo.matrix.manager import MatrixManager
from posthog.tasks.demo_create_data import HedgeboxMatrix
from posthog.test.base import NonAtomicBaseTest


@pytest.mark.skipif(os.environ.get("DEEPEVAL") != "YES", reason="Only runs for the assistant evaluation")
@flaky(max_runs=3, min_passes=1)
class EvalBaseTest(NonAtomicBaseTest):
    def _get_config(self) -> RunnableConfig:
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        return {
            "configurable": {
                "thread_id": conversation.id,
            }
        }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        matrix = HedgeboxMatrix(
            seed="b1ef3c66-5f43-488a-98be-6b46d92fbcef",  # this seed generates all events
            days_past=120,
            days_future=30,
            n_clusters=500,
            group_type_index_offset=0,
        )
        matrix_manager = MatrixManager(matrix, print_steps=True)
        existing_user = cls.team.organization.members.first()
        with override_settings(TEST=False):
            # Simulation saving should occur in non-test mode, so that Kafka isn't mocked. Normally in tests we don't
            # want to ingest via Kafka, but simulation saving is specifically designed to use that route for speed
            matrix_manager.run_on_team(cls.team, existing_user)
