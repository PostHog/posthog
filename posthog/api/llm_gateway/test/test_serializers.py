from django.test import TestCase

from posthog.api.llm_gateway.serializers import (
    AnthropicMessagesRequestSerializer,
    AnthropicMessagesResponseSerializer,
    ChatCompletionRequestSerializer,
    ChatCompletionResponseSerializer,
)


class TestAnthropicMessagesRequestSerializer(TestCase):
    def test_valid_minimal_request(self):
        data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1024,
        }
        serializer = AnthropicMessagesRequestSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["model"], "claude-3-5-sonnet-20241022")
        self.assertEqual(len(serializer.validated_data["messages"]), 1)

    def test_valid_full_request(self):
        data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 2048,
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 10,
            "stream": True,
            "stop_sequences": ["\\n\\nHuman:"],
            "system": "You are a helpful assistant",
            "metadata": {"user_id": "123"},
            "thinking": {"enabled": True},
            "tools": [{"name": "get_weather", "description": "Get weather"}],
            "tool_choice": {"type": "auto"},
            "service_tier": "auto",
        }
        serializer = AnthropicMessagesRequestSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_missing_required_model(self):
        data = {
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1024,
        }
        serializer = AnthropicMessagesRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("model", serializer.errors)

    def test_missing_required_messages(self):
        data = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1024,
        }
        serializer = AnthropicMessagesRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("messages", serializer.errors)

    def test_invalid_temperature_range(self):
        data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1024,
            "temperature": 2.0,
        }
        serializer = AnthropicMessagesRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("temperature", serializer.errors)

    def test_invalid_service_tier(self):
        data = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1024,
            "service_tier": "invalid_tier",
        }
        serializer = AnthropicMessagesRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("service_tier", serializer.errors)


class TestChatCompletionRequestSerializer(TestCase):
    def test_valid_minimal_request(self):
        data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        serializer = ChatCompletionRequestSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["model"], "gpt-4")

    def test_valid_full_request(self):
        data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
            "top_p": 0.9,
            "n": 1,
            "stream": True,
            "stream_options": {"include_usage": True},
            "stop": ["\\n"],
            "max_tokens": 1000,
            "max_completion_tokens": 1000,
            "presence_penalty": 0.5,
            "frequency_penalty": 0.5,
            "logit_bias": {"50256": -100},
            "user": "user-123",
            "tools": [{"type": "function", "function": {"name": "test"}}],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "response_format": {"type": "json_object"},
            "seed": 42,
            "logprobs": True,
            "top_logprobs": 5,
            "modalities": ["text"],
            "reasoning_effort": "medium",
            "verbosity": "standard",
            "store": False,
        }
        serializer = ChatCompletionRequestSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_missing_required_model(self):
        data = {
            "messages": [{"role": "user", "content": "Hello"}],
        }
        serializer = ChatCompletionRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("model", serializer.errors)

    def test_missing_required_messages(self):
        data = {
            "model": "gpt-4",
        }
        serializer = ChatCompletionRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("messages", serializer.errors)

    def test_invalid_temperature_range(self):
        data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 3.0,
        }
        serializer = ChatCompletionRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("temperature", serializer.errors)

    def test_invalid_top_logprobs_range(self):
        data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "top_logprobs": 25,
        }
        serializer = ChatCompletionRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("top_logprobs", serializer.errors)

    def test_invalid_reasoning_effort(self):
        data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "reasoning_effort": "invalid",
        }
        serializer = ChatCompletionRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("reasoning_effort", serializer.errors)

    def test_invalid_verbosity(self):
        data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "verbosity": "invalid",
        }
        serializer = ChatCompletionRequestSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("verbosity", serializer.errors)


class TestAnthropicMessagesResponseSerializer(TestCase):
    def test_valid_response(self):
        data = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        serializer = AnthropicMessagesResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_valid_response_with_cache(self):
        data = {
            "id": "msg_01XYZ",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 50,
            },
        }
        serializer = AnthropicMessagesResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)


class TestChatCompletionResponseSerializer(TestCase):
    def test_valid_response(self):
        data = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        serializer = ChatCompletionResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_valid_response_with_service_tier(self):
        data = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "service_tier": "default",
            "system_fingerprint": "fp_123",
        }
        serializer = ChatCompletionResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
