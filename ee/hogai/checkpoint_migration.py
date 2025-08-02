"""
Checkpoint migration utilities for converting between legacy and new state formats.

This module handles the migration of saved checkpoints from the legacy Assistant
format to the new state-specific formats (AssistantGraphState, InsightsGraphState).
"""

import structlog
from typing import Any, Optional, TypeVar
from pydantic import BaseModel, ValidationError

from ee.hogai.utils.graph_states import AssistantGraphState, InsightsGraphState

logger = structlog.get_logger(__name__)

StateType = TypeVar("StateType", bound=BaseModel)


class CheckpointMigrationError(Exception):
    """Raised when checkpoint migration fails."""

    pass


class CheckpointMigrator:
    """Handles migration of checkpoints between different state formats."""

    @staticmethod
    def detect_checkpoint_version(checkpoint_data: dict[str, Any]) -> str:
        """
        Detect the version/format of a checkpoint.

        Args:
            checkpoint_data: Raw checkpoint data

        Returns:
            String indicating the checkpoint format ("legacy", "assistant_graph", "insights_graph", "unknown")
        """
        if not isinstance(checkpoint_data, dict):
            return "unknown"

        # Check for legacy AssistantState fields
        legacy_indicators = {"mode", "root_tool_calls_count", "root_tool_insight_type"}
        if any(field in checkpoint_data for field in legacy_indicators):
            return "legacy"

        # Check for AssistantGraphState specific fields
        assistant_graph_indicators = {"graph_status", "start_id"}
        if any(field in checkpoint_data for field in assistant_graph_indicators):
            return "assistant_graph"

        # Check for InsightsGraphState specific fields
        insights_indicators = {"root_tool_insight_plan", "root_tool_insight_type", "plan"}
        if any(field in checkpoint_data for field in insights_indicators):
            return "insights_graph"

        # If it has messages, it's probably a valid state but version unknown
        if "messages" in checkpoint_data:
            return "unknown"

        return "malformed"

    @staticmethod
    def migrate_to_assistant_graph_state(checkpoint_data: dict[str, Any]) -> AssistantGraphState:
        """
        Migrate checkpoint data to AssistantGraphState format.

        Args:
            checkpoint_data: Raw checkpoint data

        Returns:
            Migrated AssistantGraphState

        Raises:
            CheckpointMigrationError: If migration fails
        """
        try:
            version = CheckpointMigrator.detect_checkpoint_version(checkpoint_data)
            logger.info(f"Migrating checkpoint from {version} to AssistantGraphState")

            if version == "assistant_graph":
                # Already in correct format
                return AssistantGraphState(**checkpoint_data)

            elif version == "legacy":
                # Migrate from legacy AssistantState
                return AssistantGraphState(
                    messages=checkpoint_data.get("messages", []),
                    graph_status=checkpoint_data.get("graph_status"),
                    start_id=checkpoint_data.get("start_id"),
                    # Skip legacy-specific fields like mode, root_tool_calls_count
                )

            elif version == "insights_graph":
                # Convert from insights format (unusual but possible)
                return AssistantGraphState(
                    messages=checkpoint_data.get("messages", []),
                    graph_status=checkpoint_data.get("graph_status"),
                    start_id=checkpoint_data.get("start_id"),
                )

            else:
                # Best effort migration for unknown/malformed checkpoints
                logger.warning(f"Unknown checkpoint format, attempting best-effort migration")
                return AssistantGraphState(
                    messages=checkpoint_data.get("messages", []),
                    graph_status=checkpoint_data.get("graph_status"),
                )

        except (ValidationError, KeyError, TypeError) as e:
            logger.exception(f"Failed to migrate checkpoint to AssistantGraphState: {str(e)}")
            raise CheckpointMigrationError(f"Migration failed: {str(e)}") from e

    @staticmethod
    def migrate_to_insights_graph_state(checkpoint_data: dict[str, Any]) -> InsightsGraphState:
        """
        Migrate checkpoint data to InsightsGraphState format.

        Args:
            checkpoint_data: Raw checkpoint data

        Returns:
            Migrated InsightsGraphState

        Raises:
            CheckpointMigrationError: If migration fails
        """
        try:
            version = CheckpointMigrator.detect_checkpoint_version(checkpoint_data)
            logger.info(f"Migrating checkpoint from {version} to InsightsGraphState")

            if version == "insights_graph":
                # Already in correct format
                return InsightsGraphState(**checkpoint_data)

            elif version == "legacy":
                # Migrate from legacy AssistantState
                return InsightsGraphState(
                    messages=checkpoint_data.get("messages", []),
                    graph_status=checkpoint_data.get("graph_status"),
                    intermediate_steps=checkpoint_data.get("intermediate_steps", []),
                    plan=checkpoint_data.get("plan"),
                    rag_context=checkpoint_data.get("rag_context"),
                    query_generation_retry_count=checkpoint_data.get("query_generation_retry_count", 0),
                    root_tool_insight_plan=checkpoint_data.get("root_tool_insight_plan"),
                    root_tool_insight_type=checkpoint_data.get("root_tool_insight_type"),
                )

            elif version == "assistant_graph":
                # Convert from assistant format
                return InsightsGraphState(
                    messages=checkpoint_data.get("messages", []),
                    graph_status=checkpoint_data.get("graph_status"),
                    # Initialize insights-specific fields with defaults
                    query_generation_retry_count=0,
                )

            else:
                # Best effort migration for unknown/malformed checkpoints
                logger.warning(f"Unknown checkpoint format, attempting best-effort migration")
                return InsightsGraphState(
                    messages=checkpoint_data.get("messages", []),
                    graph_status=checkpoint_data.get("graph_status"),
                    query_generation_retry_count=0,
                )

        except (ValidationError, KeyError, TypeError) as e:
            logger.exception(f"Failed to migrate checkpoint to InsightsGraphState: {str(e)}")
            raise CheckpointMigrationError(f"Migration failed: {str(e)}") from e

    @staticmethod
    def migrate_checkpoint(checkpoint_data: dict[str, Any], target_type: type[StateType]) -> StateType:
        """
        Generic checkpoint migration to any target state type.

        Args:
            checkpoint_data: Raw checkpoint data
            target_type: Target state class to migrate to

        Returns:
            Migrated state of the target type

        Raises:
            CheckpointMigrationError: If migration fails or target type unsupported
        """
        if target_type == AssistantGraphState:
            return CheckpointMigrator.migrate_to_assistant_graph_state(checkpoint_data)
        elif target_type == InsightsGraphState:
            return CheckpointMigrator.migrate_to_insights_graph_state(checkpoint_data)
        else:
            raise CheckpointMigrationError(f"Unsupported target type: {target_type}")

    @staticmethod
    def create_rollback_checkpoint(original_data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a rollback checkpoint that preserves original data.

        This allows rolling back to the original format if migration causes issues.

        Args:
            original_data: Original checkpoint data

        Returns:
            Rollback checkpoint with metadata
        """
        return {
            "rollback_data": original_data,
            "migration_timestamp": str(logger._context.get("timestamp", "unknown")),
            "original_version": CheckpointMigrator.detect_checkpoint_version(original_data),
        }

    @staticmethod
    def validate_migrated_checkpoint(original: dict[str, Any], migrated: BaseModel) -> bool:
        """
        Validate that migration preserved essential data.

        Args:
            original: Original checkpoint data
            migrated: Migrated state object

        Returns:
            True if validation passes, False otherwise
        """
        try:
            # Check that messages are preserved
            original_messages = original.get("messages", [])
            migrated_messages = getattr(migrated, "messages", [])

            if len(original_messages) != len(migrated_messages):
                logger.warning("Message count mismatch after migration")
                return False

            # Check that essential fields are preserved
            essential_fields = ["graph_status"]
            for field in essential_fields:
                if field in original:
                    original_value = original[field]
                    migrated_value = getattr(migrated, field, None)
                    if original_value != migrated_value:
                        logger.warning(f"Field {field} mismatch: {original_value} -> {migrated_value}")
                        return False

            logger.info("Checkpoint migration validation passed")
            return True

        except Exception as e:
            logger.exception(f"Checkpoint validation failed: {str(e)}")
            return False


def migrate_legacy_checkpoint_if_needed(
    checkpoint_data: Optional[dict[str, Any]], target_type: type[StateType]
) -> Optional[StateType]:
    """
    Convenience function to migrate a checkpoint only if needed.

    Args:
        checkpoint_data: Checkpoint data or None
        target_type: Target state type

    Returns:
        Migrated state or None if no checkpoint provided
    """
    if checkpoint_data is None:
        return None

    try:
        migrated = CheckpointMigrator.migrate_checkpoint(checkpoint_data, target_type)

        # Validate the migration
        if CheckpointMigrator.validate_migrated_checkpoint(checkpoint_data, migrated):
            logger.info(f"Successfully migrated checkpoint to {target_type.__name__}")
            return migrated
        else:
            logger.warning("Migration validation failed, returning None")
            return None

    except CheckpointMigrationError as e:
        logger.exception(f"Checkpoint migration failed: {str(e)}")
        return None
