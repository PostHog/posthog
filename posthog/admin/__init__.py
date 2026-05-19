# Lazy load admin classes to avoid loading all at startup.
# Admin classes are loaded when Django admin site is first accessed


def register_all_admin():
    """Trigger every admin registration. Called lazily on first
    `admin.site._registry` access via `LazyAdminRegistry`.

    `INSTALLED_APPS` uses `SimpleAdminConfig` so Django doesn't autodiscover at
    `django.setup()` — we run the same primitive ourselves here, deferred. That
    keeps every admin module out of `django.setup()` and out of every shell,
    worker, and management command that doesn't touch the admin.
    """
    from django.contrib import admin
    from django.utils.module_loading import autodiscover_modules

    # Imports each app's `<app>.admin` module. Every product / third-party admin
    # uses `@admin.register(Model)` at module top, which fires here.
    autodiscover_modules("admin")

    # Central PostHog admins live in `posthog/admin/admins/<x>_admin.py` —
    # submodules that `autodiscover_modules('admin')` doesn't recurse into.
    # The package's `__init__.py` re-exports them all, so a single import
    # triggers every `@admin.register` decorator in the central registry.
    import posthog.admin.admins  # noqa: F401

    # `oauth2_provider.admin` registers its own `Application` admin via
    # `@admin.register` during the autodiscover above. We want our
    # `OAuthApplicationAdmin` (custom OAuth flow, display, etc.) to win —
    # unregister the default first. This is the canonical Django pattern
    # for overriding a third-party admin.
    from posthog.admin.admins.oauth_admin import OAuthApplicationAdmin
    from posthog.models.oauth import OAuthApplication

    if admin.site.is_registered(OAuthApplication):
        admin.site.unregister(OAuthApplication)
    admin.site.register(OAuthApplication, OAuthApplicationAdmin)

    # `oauth2_provider.admin` also registers default `ModelAdmin`s for its
    # token models. Those admins expose raw token values (`token` /
    # `refresh_token` / `code`) in detail views — staff users with the
    # appropriate admin perms could read them and impersonate end users or
    # replay grants. Unregister the lot. If we ever need operational
    # visibility, re-register with an admin that redacts the secret columns
    # (same pattern as the `OAuthApplicationAdmin` override above).
    from posthog.models.oauth import OAuthAccessToken, OAuthGrant, OAuthIDToken, OAuthRefreshToken

    for model in (OAuthAccessToken, OAuthRefreshToken, OAuthGrant, OAuthIDToken):
        if admin.site.is_registered(model):
            admin.site.unregister(model)


# :KRUDGE: OAuth models live in the `posthog` app, so by default they appear
# under "PostHog" in the admin sidebar alongside dozens of unrelated models.
# The "real" fix would be to move these to `products/oauth/` so Django groups
# them automatically — but every model here is `swappable` (referenced as
# `OAUTH2_PROVIDER_APPLICATION_MODEL` etc.). Changing the app_label means
# rewriting every existing migration that points at the swappable target,
# both in oauth2_provider and in any FK that's been added on top — a known
# Django landmine. Until there's a separate reason to isolate OAuth as its
# own product, override `get_app_list` instead.
_OAUTH_ADMIN_MODEL_NAMES = frozenset(
    {
        "OAuthApplication",
        "OAuthAccessToken",
        "OAuthGrant",
        "OAuthIDToken",
        "OAuthRefreshToken",
    }
)


def install_admin_app_list_overrides():
    """Override admin sidebar grouping. Must run before any admin request so the
    first call goes through the patched function — otherwise the lazy admin
    registry would only install this mid-call after `get_app_list` has already
    started executing on the original method."""
    from django.contrib import admin
    from django.urls import NoReverseMatch, reverse

    original_get_app_list = admin.site.get_app_list

    def _build_oauth_app_dict(oauth_models):
        try:
            app_url = reverse("admin:app_list", kwargs={"app_label": "oauth"})
        except NoReverseMatch:
            app_url = ""
        return {
            "name": "OAuth",
            "app_label": "oauth",
            "app_url": app_url,
            "has_module_perms": True,
            "models": oauth_models,
        }

    def _extract_oauth_models(app_list):
        oauth_models = []
        for app in app_list:
            kept = []
            for model in app["models"]:
                if model.get("object_name") in _OAUTH_ADMIN_MODEL_NAMES:
                    oauth_models.append(model)
                else:
                    kept.append(model)
            app["models"] = kept
        return oauth_models

    def get_app_list(request, app_label=None):
        # The synthetic "oauth" app_label has no real models registered against it,
        # so we have to source its models from the `posthog` app and rebuild the
        # group ourselves — otherwise visiting /admin/oauth/ would 404.
        if app_label == "oauth":
            posthog_app_list = original_get_app_list(request, app_label="posthog")
            oauth_models = _extract_oauth_models(posthog_app_list)
            oauth_models.sort(key=lambda model: model["name"].lower())
            return [_build_oauth_app_dict(oauth_models)] if oauth_models else []

        app_list = original_get_app_list(request, app_label=app_label)
        oauth_models = _extract_oauth_models(app_list)
        if not oauth_models:
            return app_list

        oauth_models.sort(key=lambda model: model["name"].lower())
        app_list = [app for app in app_list if app["models"]]
        app_list.append(_build_oauth_app_dict(oauth_models))
        app_list.sort(key=lambda app: app["name"].lower())
        return app_list

    admin.site.get_app_list = get_app_list  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
