# Icons and mixins

## Icons

- Prefer SVG over PNG. Keep file size reasonable.
- Place in `frontend/public/services/` and reference as `/static/services/{name}.svg` in `iconPath`.
- If the source logo isn't already in the project, pull via [Logo.dev](https://docs.logo.dev/introduction). **Ask the user for the API key** — do not hardcode one. If the user hasn't provided one, surface that as a blocker rather than committing a placeholder.

## Mixins

From `products/warehouse_sources/backend/temporal/data_imports/sources/common/mixins.py`:

- `SSHTunnelMixin` — `with_ssh_tunnel()` context plus `make_ssh_tunnel_func()` for deferred tunnel opening.
- `OAuthMixin` — `get_oauth_integration()` to pull `Integration` from the DB.
- `ValidateDatabaseHostMixin` — `is_database_host_valid()` to block internal VPC IPs (unless SSH tunnel is used).
