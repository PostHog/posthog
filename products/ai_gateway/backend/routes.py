from posthog.api.routing import RouterRegistry


def register_routes(routers: RouterRegistry) -> None:
    # AI gateway has no per-team management resource: a project secret key with the
    # llm_gateway:read scope reaches the gateway directly, and usage is read from events.
    pass
