from django.apps import apps


def test_ai_gateway_app_is_registered() -> None:
    config = apps.get_app_config("ai_gateway")
    assert config.name == "products.ai_gateway.backend"
