from uuid import uuid4

from unittest.mock import MagicMock, patch

from products.data_warehouse.backend.api import managed_warehouse


@patch("products.data_warehouse.backend.api.managed_warehouse.posthoganalytics.feature_enabled")
def test_is_enabled_uses_data_warehouse_scene_flag(mock_feature_enabled: MagicMock) -> None:
    organization_id = uuid4()
    mock_feature_enabled.return_value = True

    assert managed_warehouse.is_enabled(organization_id) is True

    mock_feature_enabled.assert_called_once_with(
        "data-warehouse-scene",
        str(organization_id),
        groups={"organization": str(organization_id)},
        group_properties={"organization": {"id": str(organization_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
