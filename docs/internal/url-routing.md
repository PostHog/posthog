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

Product DRF routes continue to register through `products/<product>/backend/routes.py`.
Root-level product routes remain explicit in `posthog/urls.py`.
