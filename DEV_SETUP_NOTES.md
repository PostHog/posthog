**Goal**
- Minimal local dev using `bin/start --minimal` with the fewest code changes.

**Environment Prereqs**
- Docker Desktop/Engine + Compose v2; user in `docker` group.
- Node 22.x + `pnpm` via Corepack.
- Python 3.11 available as `python` (symlinked to uv-managed Python).
- Rust toolchain (`cargo`) for local Rust services.

**Installed Tools**
- **mprocs**: process TUI required by `bin/start`.
- **pnpm**: `sudo corepack enable && sudo corepack prepare pnpm@9.15.5 --activate`.
- **uv**: Python package/venv manager, plus Python 3.11.

**One-Time System Tweaks**
- **Docker group**: add user to `docker` group and re-login.
- **`python` symlink**: `sudo ln -sf ~/.local/bin/python3.11 /usr/local/bin/python`.
- Optional: add `127.0.0.1 clickhouse` to `/etc/hosts` if name resolution is flaky.

**Repo Local Overrides**
- Added `.env` (auto-loaded by `bin/start`) to point host-run processes to Docker services:
  - `CLICKHOUSE_HOST=localhost`
  - `CLICKHOUSE_MIGRATIONS_HOST=localhost`
  - `CLICKHOUSE_LOGS_CLUSTER_HOST=localhost`
  - `KAFKA_HOSTS=localhost:9092`
  - `REDIS_URL=redis://localhost:6379`

**Complete Setup Workflow**
1. **Install Dependencies**:
   ```bash
   # Python dependencies
   uv sync
   
   # JavaScript dependencies  
   pnpm install
   ```

2. **Activate Virtual Environment**:
   ```bash
   source .venv/bin/activate
   ```

3. **Start PostHog**:
   ```bash
   bin/start --minimal
   ```

4. **Optional - Capture Logs** (for debugging):
   ```bash
   script -q -f -c "source .venv/bin/activate && bin/start --minimal" logs/mprocs-$(date +%F-%H%M%S).log
   ```

**Quick Start Command**
- From an activated venv (recommended):
  - `uv sync && source .venv/bin/activate && bin/start --minimal`

**What Runs In Minimal**
- Docker: Postgres, Redis, Redis7, ClickHouse, Zookeeper, Kafka, Object Storage, Proxy.
- Host processes: Backend (Uvicorn), Celery worker, Plugin server, Frontend (Vite), Rust services.

**Common Issues & Fixes**
- **Docker socket permission denied**:
  - Symptom: `permission denied while trying to connect to the Docker daemon socket`.
  - Fix: add user to `docker` group, re-login; quick workaround: start compose with `sudo` once.
- **Feature-flags GeoIP permission**:
  - Symptom: `Failed to open GeoIP database: IoError: Permission denied`.
  - Fix: `chmod 644 share/GeoLite2-City.mmdb` (downloaded by `bin/download-mmdb`).
- **Django not installed**:
  - Symptom: `ModuleNotFoundError: No module named 'django'` in backend pane.
  - Fix: `uv sync` then `source .venv/bin/activate` before `bin/start`.
- **ClickHouse name resolution (migrate-clickhouse)**:
  - Symptom: `Temporary failure in name resolution (clickhouse:9000)`.
  - Fix: use `.env` overrides above; alternatively add `/etc/hosts` alias for `clickhouse`.
- **See everything**:
  - Use `script` to capture `mprocs` output; scan for errors with ripgrep.

**Verification**
- App UI: `http://localhost:8010` (proxy to backend).
- Health: `http://localhost:8010/_health`.
- ClickHouse HTTP: `http://localhost:8123`.
- MinIO console: `http://localhost:19001`.

**Current Status (2024-08-30)**
- ✅ Dependencies verified: mprocs, uv, pnpm, docker all installed
- ✅ Python deps installed: `uv sync` completed successfully  
- ✅ JS deps installed: `pnpm install` completed with some peer dep warnings
- ✅ **PostHog running successfully!** `bin/start --minimal` working after activating venv

**Success!**
- All core services are UP: backend, celery-worker, plugin-server, frontend, docker-compose, property-defs-rs, capture, feature-flags, migrate-clickhouse
- Only celery-beat is DOWN (expected - set to autostart: false in minimal config)
- App should be accessible at http://localhost:8010

**Notes**
- We avoided code changes; the only repo additions were `.env` and this doc.
- Optional follow-up: add a `chmod 644` step to `bin/download-mmdb` to prevent GeoIP permission loops on fresh setups.
