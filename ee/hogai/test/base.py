from typing import Any, cast

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from azure.ai.inference import EmbeddingsClient
from azure.ai.inference.models import EmbeddingsResult, EmbeddingsUsage
from azure.core.credentials import AzureKeyCredential
from pydantic import BaseModel

from posthog.schema import AssistantEventType

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import AssistantOutput
from ee.models.assistant import Conversation, CoreMemory


class BaseAssistantTest(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.core_memory = CoreMemory.objects.create(
            team=self.team,
            text="Initial memory.",
            initial_text="Initial memory.",
            scraping_status=CoreMemory.ScrapingStatus.COMPLETED,
        )
        self.checkpointer_patch = patch("ee.hogai.core.base.global_checkpointer", new=DjangoCheckpointer())
        self.checkpointer_patch.start()
        # Azure embeddings mocks
        self.azure_client_mock = patch(
            "ee.hogai.chat_agent.rag.nodes.get_azure_embeddings_client",
            return_value=EmbeddingsClient(
                endpoint="https://test.services.ai.azure.com/models", credential=AzureKeyCredential("test")
            ),
        ).start()
        self.embed_query_mock = patch(
            "azure.ai.inference.EmbeddingsClient.embed",
            return_value=EmbeddingsResult(
                id="test",
                model="test",
                usage=EmbeddingsUsage(prompt_tokens=1, total_tokens=1),
                data=[],
            ),
        ).start()

    def tearDown(self):
        self.checkpointer_patch.stop()
        self.azure_client_mock.stop()
        self.embed_query_mock.stop()
        super().tearDown()

    def assertConversationEqual(self, output: list[AssistantOutput], expected_output: list[tuple[Any, Any]]):
        self.assertEqual(len(output), len(expected_output), output)
        for i, ((output_msg_type, output_msg), (expected_msg_type, expected_msg)) in enumerate(
            zip(output, expected_output)
        ):
            if (
                output_msg_type == AssistantEventType.CONVERSATION
                and expected_msg_type == AssistantEventType.CONVERSATION
            ):
                self.assertEqual(output_msg, expected_msg)
            elif (
                output_msg_type == AssistantEventType.MESSAGE and expected_msg_type == AssistantEventType.MESSAGE
            ) or (output_msg_type == AssistantEventType.UPDATE and expected_msg_type == AssistantEventType.UPDATE):
                msg_dict = (
                    expected_msg.model_dump(exclude_none=True) if isinstance(expected_msg, BaseModel) else expected_msg
                )
                msg_dict.pop("id", None)
                output_msg_dict = cast(BaseModel, output_msg).model_dump(exclude_none=True)
                output_msg_dict.pop("id", None)
                self.assertLessEqual(
                    msg_dict.items(),
                    output_msg_dict.items(),
                    f"Message content mismatch at index {i}",
                )
            else:
                raise ValueError(f"Unexpected message type: {output_msg_type} and {expected_msg_type}")

    def assertStateMessagesEqual(self, messages: list[Any], expected_messages: list[Any]):
        self.assertEqual(len(messages), len(expected_messages))
        for i, (message, expected_message) in enumerate(zip(messages, expected_messages)):
            expected_msg_dict = (
                expected_message.model_dump(exclude_none=True)
                if isinstance(expected_message, BaseModel)
                else expected_message
            )
            expected_msg_dict.pop("id", None)
            msg_dict = message.model_dump(exclude_none=True) if isinstance(message, BaseModel) else message
            msg_dict.pop("id", None)
            self.assertLessEqual(expected_msg_dict.items(), msg_dict.items(), f"Message content mismatch at index {i}")
