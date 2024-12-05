# type: ignore

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    Checkpoint,
    CheckpointMetadata,
    create_checkpoint,
    empty_checkpoint,
)

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.models.assistant import AssistantThread
from posthog.test.base import BaseTest


class TestDjangoCheckpointer(BaseTest):
    def setUp(self):
        super().setUp()

        self.thread1 = AssistantThread.objects.create(user=self.user, team=self.team)
        self.thread2 = AssistantThread.objects.create(user=self.user, team=self.team)

        config_1: RunnableConfig = {
            "configurable": {
                "thread_id": self.thread1.id,
                "checkpoint_ns": "",
            }
        }
        chkpnt_1: Checkpoint = empty_checkpoint()

        config_2: RunnableConfig = {
            "configurable": {
                "thread_id": self.thread2.id,
                "checkpoint_ns": "",
            }
        }
        chkpnt_2: Checkpoint = create_checkpoint(chkpnt_1, {}, 1)

        config_3: RunnableConfig = {
            "configurable": {
                "thread_id": self.thread2.id,
                "checkpoint_id": chkpnt_2["id"],
                "checkpoint_ns": "inner",
            }
        }
        chkpnt_3: Checkpoint = empty_checkpoint()

        metadata_1: CheckpointMetadata = {
            "source": "input",
            "step": 2,
            "writes": {},
            "score": 1,
        }
        metadata_2: CheckpointMetadata = {
            "source": "loop",
            "step": 1,
            "writes": {"foo": "bar"},
            "score": None,
        }
        metadata_3: CheckpointMetadata = {}

        self.test_data = {
            "configs": [config_1, config_2, config_3],
            "checkpoints": [chkpnt_1, chkpnt_2, chkpnt_3],
            "metadata": [metadata_1, metadata_2, metadata_3],
        }

    def test_saver(self):
        saver = DjangoCheckpointer()
        test_data = self.test_data

        configs = test_data["configs"]
        checkpoints = test_data["checkpoints"]
        metadata = test_data["metadata"]

        saver.put(configs[0], checkpoints[0], metadata[0], {})
        saver.put(configs[1], checkpoints[1], metadata[1], {})
        saver.put(configs[2], checkpoints[2], metadata[2], {})

        # call method / assertions
        query_1 = {"source": "input"}  # search by 1 key
        query_2 = {
            "step": 1,
            "writes": {"foo": "bar"},
        }  # search by multiple keys
        query_3: dict[str, Any] = {}  # search by no keys, return all checkpoints
        query_4 = {"source": "update", "step": 1}  # no match

        search_results_1 = list(saver.list(None, filter=query_1))
        assert len(search_results_1) == 1
        assert search_results_1[0].metadata == metadata[0]

        search_results_2 = list(saver.list(None, filter=query_2))
        assert len(search_results_2) == 1
        assert search_results_2[0].metadata == metadata[1]

        search_results_3 = list(saver.list(None, filter=query_3))
        assert len(search_results_3) == 3

        search_results_4 = list(saver.list(None, filter=query_4))
        assert len(search_results_4) == 0

        # search by config (defaults to checkpoints across all namespaces)
        search_results_5 = list(saver.list({"configurable": {"thread_id": self.thread2.id}}))
        assert len(search_results_5) == 2
        assert {
            search_results_5[0].config["configurable"]["checkpoint_ns"],
            search_results_5[1].config["configurable"]["checkpoint_ns"],
        } == {"", "inner"}
