# URL routing — discovery architecture and env-alias mechanics

The rules (canonical path, `routes.py` registration snippet, the don'ts) are in the main skill; this is the background.

## Why two path families exist

PostHog briefly split projects and environments as separate concepts then rolled the split back.
`/api/projects/:team_id/...` is the canonical path for any team-nested endpoint.
`/api/environments/:team_id/...` is a backward-compat alias preserved only for clients that integrated against it during the split.

## How product routes are discovered

Product routes are auto-discovered — `posthog/api/__init__.py` iterates `INSTALLED_APPS` and calls `register_routes(routers)` on every `products.*` app that has a `routes.py`.
Adding a product needs no edit to core: create `products/<name>/backend/routes.py` and make sure the product is in `PRODUCTS_APPS` (`posthog/settings/web.py`).
Only core, non-product viewsets still register directly in `__init__.py`.

**Why core discovers and calls the product (not the product calling core).**
Core registers the four parents (`root` + `projects`/`environments`/`organizations`) first, then runs the discovery loop.
Products only nest onto those parents and never onto each other, so discovery order is irrelevant.
The registration is kept eager (it runs when `posthog.api` is first imported, i.e. on the first request) and deliberately _not_ moved into `AppConfig.ready()`: `ready()` runs inside `django.setup()` in every process, and registering a route imports its viewset, so that would pull the whole API into `setup()` everywhere — regressing the laziness that keeps the API out of Celery workers and management commands.
See the `RouterRegistry` docstring and the discovery loop in `posthog/api/__init__.py` for the full reasoning.

## Dual-route helpers and deprecation

Do not register new endpoints under `environments_router`.
Do not use the dual-route helper (`routers.register_legacy_dual_route`, or `register_legacy_dual_route_team_nested_viewset` in `__init__.py`) — it exists only for endpoints already exposed on both `/api/projects/` and `/api/environments/` before the rollback.

If existing clients need `/api/environments/...` too, the OpenAPI postprocess hook at `posthog.api.documentation.preprocess_exclude_path_format` auto-marks the env-side path as `deprecated: true` whenever both routes exist.
