# Root URL routing

`posthog/urls.py` declares the ordered root `urlpatterns` and imports Django's `handler500` binding.
View implementations live outside the URL configuration.

- `posthog/frontend_views.py` renders the frontend and redirects visitors to their logged-in cloud region before the login check.
- `posthog/api/integration_connect.py` starts integration connection flows.
- `posthog/api/oauth/toolbar_views.py` handles toolbar and forum authorization redirects.
- `posthog/views.py` owns the server-error and debug metrics views alongside the existing operational views.
- `posthog/api/playwright_setup.py` owns test setup and the test-only event deletion view.
- `posthog/ee_urls.py` loads optional Enterprise routes and extends the API router before its URLs are evaluated.

Keep routing declarative and preserve precedence when adding an entry.
The EU personal-spend override comes before the API router.
The API fallback comes after API endpoints.
GitHub and Slack identity callbacks come before the generic social-auth routes.
Public frontend routes come before the authenticated catch-all, which stays last.

The metrics endpoint is available only with `DEBUG`.
Event deletion is available only with `TEST`.
The Temporal codec endpoint is registered once when either setting is enabled.
These conditions control registration, not only view behavior.

## Product root routes

A product declares its root paths in `products/<product>/backend/routes.py`, as a `urlpatterns` list beside `register_routes`.
`posthog/product_urls.py` collects every product's list, and `posthog/urls.py` splices it into one slot: after all core routes, and before the `^api.+` fallback and the frontend catch-all.
Precedence stays one list to read, and a product that adds a path does not touch core.

Each pattern must start with `api/<product>/` or `webhooks/<product>/`, where `<product>` is the product directory name.
A pattern outside those prefixes raises `ProductRouteError` when the URL conf loads.
The check is fail-closed because a product path in core's namespace can shadow a core route, and the winner would then depend on app iteration order.

`register_routes(routers)` stays the way to add DRF routes.
Use `urlpatterns` only for a plain Django path that no router can carry, such as an inbound webhook endpoint.

### Who owns a webhook route

The owner of the third-party App registration owns the route.
The customer-facing GitHub App is shared: one endpoint fans out to several products, so core mounts it.
An App a single product registers, such as Stamphog's GitHub App, is mounted by that product.
A topic a single product owns works the same way: `webhooks/workflows/ses-events` is mounted from `products/workflows/backend/routes.py`.
