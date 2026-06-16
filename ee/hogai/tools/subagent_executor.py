# SubagentExecutor lives in its own module (not in task.py) on purpose: subclassing AgentExecutor
# requires importing ee.hogai.core.executor at module load, which reaches back into ee.hogai.tools
# through posthog.temporal.ai -> chat_agent -> toolkit. Keeping it here lets task.py import it lazily
# inside _arun_impl, so importing the `task` tool never drags the agent core onto the module path —
# while staying a real top-level class that can be imported and patched in tests.
from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.core.executor import AgentExecutor
from ee.hogai.stream.redis_stream import get_subagent_stream_key


class SubagentExecutor(AgentExecutor):
    """Executor for subagent workflows that uses a tool-specific stream key."""

    def __init__(self, conversation: Conversation, tool_call_id: str, execution_id: str):
        # Include execution_id to make workflow IDs unique per execution,
        # preventing conflicts when tool calls are replayed from checkpoints
        stream_key = get_subagent_stream_key(conversation.id, f"{tool_call_id}-{execution_id}")
        super().__init__(conversation, stream_key, reconnectable=False)
        self._workflow_id = f"subagent-{conversation.id}-{tool_call_id}-{execution_id}"
