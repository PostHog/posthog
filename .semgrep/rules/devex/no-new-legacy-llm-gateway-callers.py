from django.conf import settings

from posthog.llm.gateway_client import build_openai_client, get_async_anthropic_gateway_client, get_llm_client
from posthog.llm import gateway_client


def legacy_callers(team_id: int) -> None:
    # ruleid: no-new-legacy-llm-gateway-callers-python
    get_llm_client(product="web_analytics", team_id=team_id)
    # ruleid: no-new-legacy-llm-gateway-callers-python
    get_async_anthropic_gateway_client(product="signals", team_id=team_id)
    # ruleid: no-new-legacy-llm-gateway-callers-python
    gateway_client.get_async_llm_client(product="django")
    # ruleid: no-new-legacy-llm-gateway-callers-python
    url = settings.LLM_GATEWAY_URL
    # ruleid: no-new-legacy-llm-gateway-callers-python
    key = getattr(settings, "LLM_GATEWAY_API_KEY", "")
    # ruleid: no-new-legacy-llm-gateway-callers-python
    env = {"SANDBOX_LLM_GATEWAY_URL": url}
    # ruleid: no-new-legacy-llm-gateway-callers-python
    host = "https://gateway.us.posthog.com/posthog_code"
    # ruleid: no-new-legacy-llm-gateway-callers-python
    in_cluster = "http://llm-gateway.llm-gateway.svc.cluster.local:8080"


def go_callers() -> None:
    # ok: no-new-legacy-llm-gateway-callers-python
    build_openai_client("web_analytics", ai_product="web_analytics")
    # ok: no-new-legacy-llm-gateway-callers-python
    url = settings.AI_GATEWAY_URL
    # ok: no-new-legacy-llm-gateway-callers-python
    host = "https://ai-gateway.us.posthog.com/v1"
    print(url, host)
