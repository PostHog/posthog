import structlog

from posthog.models.instance_setting import set_instance_setting

from products.ai_observability.backend.dataset_retention import RETENTION_ENABLED_SETTING, dataset_retention_enabled

logger = structlog.get_logger(__name__)


def set_dataset_retention_enabled(*, enabled: bool, user_id: int) -> None:
    previous_enabled = dataset_retention_enabled()
    set_instance_setting(RETENTION_ENABLED_SETTING, enabled)
    logger.info(
        "dataset_retention_setting_changed", user_id=user_id, previous_enabled=previous_enabled, enabled=enabled
    )
