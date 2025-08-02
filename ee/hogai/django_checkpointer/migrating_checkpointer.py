"""
Migrating Django Checkpointer that handles state type migrations.

This checkpointer extends DjangoCheckpointer to automatically migrate
checkpoints from legacy AssistantState to graph-specific states.
"""

from typing import Optional, Any
from collections.abc import AsyncIterator

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import CheckpointTuple

from ee.hogai.django_checkpointer.checkpointer import DjangoCheckpointer
from ee.hogai.checkpoint_migration import migrate_legacy_checkpoint_if_needed
from ee.hogai.states.graph_states import AssistantGraphState, InsightsGraphState
import structlog

logger = structlog.get_logger(__name__)


class MigratingDjangoCheckpointer(DjangoCheckpointer):
    """
    Django checkpointer that automatically migrates legacy checkpoints.

    This checkpointer detects the graph type from the checkpoint namespace
    and automatically converts legacy AssistantState checkpoints to the
    appropriate graph-specific state type.
    """

    def _get_target_state_type(self, checkpoint_ns: str) -> type:
        """
        Determine the target state type based on checkpoint namespace.

        Args:
            checkpoint_ns: The checkpoint namespace

        Returns:
            The appropriate state class for this namespace
        """
        if not checkpoint_ns:
            # Root graph uses AssistantGraphState
            return AssistantGraphState
        elif checkpoint_ns == "insights_subgraph":
            # Only the actual insights subgraph uses InsightsGraphState
            return InsightsGraphState
        elif "memory" in checkpoint_ns.lower():
            # When MemoryGraphState is implemented
            return AssistantGraphState  # Fallback for now
        else:
            # All other namespaces (including insights_search) use AssistantGraphState
            # because they are nodes in the main assistant graph
            return AssistantGraphState

    def _migrate_checkpoint_data(self, checkpoint_data: dict[str, Any], checkpoint_ns: str) -> dict[str, Any]:
        """
        Migrate checkpoint data if needed.

        Args:
            checkpoint_data: The raw checkpoint data
            checkpoint_ns: The checkpoint namespace

        Returns:
            Migrated checkpoint data
        """
        # Get the channel values from the checkpoint
        channel_values = checkpoint_data.get("channel_values", {})

        # Skip if no channel values
        if not channel_values:
            return checkpoint_data

        # The state is typically in the first channel (e.g., '__start__' or the graph's state channel)
        # Find the state channel - it's usually the one that contains our state data
        state_channel = None
        state_data = None

        for channel, value in channel_values.items():
            # Look for channels that contain state-like data
            if isinstance(value, dict) and any(key in value for key in ["messages", "graph_status", "start_id"]):
                state_channel = channel
                state_data = value
                break

        if not state_channel or not state_data:
            # No state data found, return as-is
            return checkpoint_data

        # Determine target state type
        target_type = self._get_target_state_type(checkpoint_ns)

        # Migrate the state data
        migrated_state = migrate_legacy_checkpoint_if_needed(state_data, target_type)

        if migrated_state:
            # Update the checkpoint with migrated state
            checkpoint_data = checkpoint_data.copy()
            checkpoint_data["channel_values"] = channel_values.copy()
            checkpoint_data["channel_values"][state_channel] = migrated_state.model_dump()

            logger.info(
                "Migrated checkpoint state",
                checkpoint_ns=checkpoint_ns,
                target_type=target_type.__name__,
                state_channel=state_channel,
            )

        return checkpoint_data

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """
        List checkpoints with automatic migration.

        This method extends the parent's alist to automatically migrate
        legacy checkpoints as they are loaded.
        """
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "") if config else ""

        async for checkpoint_tuple in super().alist(config, filter=filter, before=before, limit=limit):
            # Extract the checkpoint data
            config_data, checkpoint_data, metadata, parent_config, writes = checkpoint_tuple

            # Migrate if needed
            migrated_checkpoint = self._migrate_checkpoint_data(checkpoint_data, checkpoint_ns)

            # Yield the migrated tuple
            yield CheckpointTuple(
                config_data,
                migrated_checkpoint,
                metadata,
                parent_config,
                writes,
            )

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """
        Get a checkpoint tuple with automatic migration.

        This method extends the parent's aget_tuple to automatically migrate
        legacy checkpoints as they are loaded.
        """
        checkpoint_tuple = await super().aget_tuple(config)

        if not checkpoint_tuple:
            return None

        # Extract checkpoint namespace
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")

        # Extract the checkpoint data
        config_data, checkpoint_data, metadata, parent_config, writes = checkpoint_tuple

        # Migrate if needed
        migrated_checkpoint = self._migrate_checkpoint_data(checkpoint_data, checkpoint_ns)

        # Return the migrated tuple
        return CheckpointTuple(
            config_data,
            migrated_checkpoint,
            metadata,
            parent_config,
            writes,
        )
