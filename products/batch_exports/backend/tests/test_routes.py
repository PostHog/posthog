import pytest
from unittest.mock import MagicMock

from products.batch_exports.backend.routes import register_routes


@pytest.mark.parametrize("enabled", [True, False])
def test_api_routes_exist_only_while_batch_exports_are_on(settings, enabled: bool):
    settings.BATCH_EXPORTS_ENABLED = enabled
    routers = MagicMock()

    register_routes(routers)

    assert routers.projects.register.called is enabled
