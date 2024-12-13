import os

import pytest

# from flaky import flaky
from langchain_core.runnables import RunnableConfig

from ee.models.assistant import Conversation
from posthog.test.base import NonAtomicBaseTest


@pytest.mark.skipif(os.environ.get("DEEPEVAL") != "YES", reason="Only runs for the assistant evaluation")
# @flaky(max_runs=3, min_passes=1)
class EvalBaseTest(NonAtomicBaseTest):
    def _get_config(self) -> RunnableConfig:
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        return {
            "configurable": {
                "thread_id": conversation.id,
            }
        }
