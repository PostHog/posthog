from datetime import datetime, UTC
from typing import Any
import logging

from ee.models.assistant import ConversationCheckpoint
from .registry import registry

from .base import BaseMigration
from ee.hogai.utils.types import GraphContext, GraphType, VersionMetadata

logger = logging.getLogger(__name__)


class Migration0001(BaseMigration):
    """
    Migration 0001: Add version metadata to legacy state objects.

    This migration transforms v0 (unversioned) state objects to v1 (versioned)
    by adding VersionMetadata fields that enable future migration routing.

    - Detects legacy state objects in checkpoint blobs that lack version_metadata
    - Adds VersionMetadata with schema_version=1 to these state objects
    - Saves the migrated state objects back to the database
    - Marks checkpoint metadata with migration tracking info

    After this migration:
    - All existing checkpoints will have version_metadata in their state objects
    - New checkpoints should be created with version_metadata from the start
    - Future migrations (0002+) can assume version_metadata exists
    - The migration system can then route transformations based on version_metadata
    """

    @staticmethod
    def needs_migration(state_obj: Any) -> bool:
        """
        Check if a state object needs Migration 0001.

        Migration 0001 is needed if the state object lacks version_metadata.
        This is specific to Migration 0001 - future migrations will have
        different detection logic based on version_metadata content.

        Args:
            state_obj: Decoded state object from checkpoint blob

        Returns:
            True if Migration 0001 is needed, False otherwise
        """
        # Check BaseState instances (AssistantState, FilterOptionsState)
        if hasattr(state_obj, "version_metadata"):
            return state_obj.version_metadata is None

        # Check dict-based state data (partial updates, legacy formats)
        if isinstance(state_obj, dict):
            # Skip if already has version metadata
            if "version_metadata" in state_obj:
                return False

            # Check if this looks like state data by examining fields
            state_indicators = {
                "messages",
                "start_id",
                "graph_status",
                "plan",
                "intermediate_steps",
                "root_tool_call_id",
                "rag_context",
                "query_generation_retry_count",
                "onboarding_question",
                "current_filters",
                "generated_filter_options",
                "change",
            }

            return bool(state_indicators.intersection(state_obj.keys()))

        return False

    @staticmethod
    def apply_to_state_object(state_obj: Any, graph_type: GraphType, context: GraphContext) -> Any:
        """
        Apply Migration 0001 to a state object by adding VersionMetadata.

        This is the core transformation logic for Migration 0001 that adds
        version_metadata to state objects that don't have it.

        Args:
            state_obj: The state object to migrate
            graph_type: Graph type for migration context
            context: Context for migration context

        Returns:
            Migrated state object with version_metadata added
        """
        if not Migration0001.needs_migration(state_obj):
            return state_obj

        # Create version metadata for Migration 0001
        version_meta = VersionMetadata(
            schema_version=Migration0001.get_version(),
            migrated_at=datetime.now(UTC).isoformat(),
            graph_type=graph_type,
            context=context,
        )

        # Handle BaseState instances (AssistantState, FilterOptionsState)
        if hasattr(state_obj, "version_metadata"):
            try:
                state_dict = state_obj.model_dump()
                state_dict["version_metadata"] = version_meta
                migrated_obj = type(state_obj)(**state_dict)
                return migrated_obj

            except Exception as e:
                logger.warning(
                    f"Migration 0001: Failed to recreate BaseState object "
                    f"({type(state_obj).__name__}): {e}, using dict fallback"
                )
                state_dict = state_obj.__dict__.copy()
                state_dict["version_metadata"] = version_meta.model_dump(mode="json")
                return state_dict

        # Handle dict-based state data
        elif isinstance(state_obj, dict):
            migrated_dict = state_obj.copy()
            migrated_dict["version_metadata"] = version_meta.model_dump(mode="json")

            return migrated_dict

        # For non-state objects, return unchanged
        return state_obj

    @classmethod
    def detect_graph_context(cls, checkpoint: ConversationCheckpoint) -> tuple[GraphType, GraphContext]:
        """
        Detect graph type, state type, and context from checkpoint namespace.

        This is Migration 0001 specific logic for detecting context from legacy
        checkpoints.

        Args:
            checkpoint_ns: LangGraph checkpoint namespace
            conversation_type: Conversation type from thread model

        Returns:
            Tuple of (graph_type, state_type, context)
        """
        checkpoint_ns = checkpoint.checkpoint_ns
        conversation_type = checkpoint.thread.type if checkpoint.thread else "assistant"

        # Analyze namespace patterns to determine graph context
        if "root_tools:" in checkpoint_ns:
            # FilterOptions graph runs within root_tools subgraph
            return (GraphType.FILTER_OPTIONS, GraphContext.SUBGRAPH)
        elif "insights_subgraph:" in checkpoint_ns:
            # Insights subgraph still uses AssistantState but different context
            return (GraphType.INSIGHTS, GraphContext.SUBGRAPH)
        elif conversation_type == "insights_tool":
            # Tool call context for insights
            return (GraphType.INSIGHTS, GraphContext.ROOT)
        else:
            # Main assistant graph (empty namespace)
            return (GraphType.ASSISTANT, GraphContext.ROOT)


# Register Migration 0001 with the registry
registry.register_migration(Migration0001)
