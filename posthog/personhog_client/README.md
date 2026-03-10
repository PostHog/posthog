# personhog_client

Python gRPC client for the personhog service.

- `client.py` — `PersonHogClient` with typed methods for each RPC, plus `get_personhog_client()` singleton
- `gate.py` — `use_personhog()` rollout gate (`PERSONHOG_ENABLED`, `PERSONHOG_ADDR`, `PERSONHOG_ROLLOUT_PERCENTAGE`)
- `proto/generated/` — auto-generated stubs (do not edit)
- `proto/__init__.py` — convenience re-exports

For updating proto definitions, see [`proto/README.md`](/proto/README.md).
