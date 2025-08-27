# PostHog Dev Notes (local + VM)

These are working notes to stand PostHog up quickly for local/dev usage and to capture fixes for common pitfalls we hit.

## Overview

- Repo/branch: this folder contains a fork of `posthog/posthog` on branch `dev-setup`.
- Primary compose files:
  - `docker-compose.dev-full.yml` – run everything in containers (dev experience).
  - `docker-compose.base.yml` – service definitions shared by all compose configs.
- Extra logs (kept outside this folder):
  - `~/compose_up.log` and `~/compose_migrate.log` – ad‑hoc logs we teed into.

## Current State (working)

- Core infra running: Postgres, Redis, Zookeeper, Kafka (Redpanda), ClickHouse, MinIO, Maildev.
- Services running: `capture`, `replay-capture`, `feature-flags`, `web`, `proxy`.
- Access (via proxy): `http://localhost:8010` (or `http://<vm-ip>:8010` on a VM).
- Validated endpoints:
  - Proxy: `/_health` => `200 ok`, `/login` => PostHog HTML.
  - Web: `/_health` => `200 ok`.

## Quick Start

1) Start core infra and stateless services (first time may pull images):

```bash
docker compose -f docker-compose.dev-full.yml up -d db redis zookeeper kafka clickhouse objectstorage maildev
docker compose -f docker-compose.dev-full.yml up -d feature-flags capture replay-capture
```

2) Build app images (long):

```bash
docker compose -f docker-compose.dev-full.yml build --pull | tee -a ~/compose_up.log
```

3) Run migrations (DEBUG=0 with a secret for safety):

```bash
docker compose -f docker-compose.dev-full.yml run --rm -e DEBUG=0 -e SECRET_KEY="$(openssl rand -hex 32)" migrate | tee -a ~/compose_migrate.log
```

4) Start app + proxy (with overrides below):

```bash
docker compose \
  -f docker-compose.dev-full.yml \
  -f docker-compose.debug-off.yml \
  -f docker-compose.proxy-caddyfile.yml \
  up -d web proxy
```

5) Visit the UI: `http://localhost:8010` (or VM external IP + `:8010`).

## Overrides Added (in this repo)

### 1) `docker-compose.debug-off.yml`

Purpose: keep `web` in DEBUG=1 (dev UX, avoids production-only warnings) while allowing migrations to run with `DEBUG=0` when needed.

```yaml
services:
  web:
    environment:
      DEBUG: "1"
      SECRET_KEY: "change-me-please-dev"
  migrate:
    environment:
      DEBUG: "0"
```

### 2) `docker-compose.proxy-caddyfile.yml`

Purpose: inject a host‑agnostic Caddyfile so proxy accepts any Host and routes traffic to the correct backends.

```yaml
services:
  proxy:
    environment:
      CADDYFILE: |
        :8000 {
            @replay-capture { path /s path /s/* }
            @capture { path /e path /e/* path /i/v0 path /i/v0/* path /batch path /batch/* path /capture path /capture/* }
            @flags { path /flags path /flags/* }
            @webhooks { path /public/webhooks path /public/webhooks/* path /public/m/ path /public/m/* }
            handle @capture { reverse_proxy capture:3000 }
            handle @replay-capture { reverse_proxy replay-capture:3000 }
            handle @flags { reverse_proxy feature-flags:3001 }
            handle @webhooks { reverse_proxy plugins:6738 }
            handle { reverse_proxy web:8000 }
        }
```

Apply proxy + debug overrides together with the main compose file (see Quick Start step 4).

## Notes and Fixes We Hit

1) Docker build failures / disk space
- Symptoms: `no space left on device`, Dockerfile `fetch-geoip-db` stage exit code 100 (apt cache space).
- Fix: free space (`docker image prune -af`, `docker builder prune -af`) and re‑run build.

2) Services restart loop (`capture`, `feature-flags`, `replay-capture`)
- Symptoms: Services continuously restarting with Redis connection errors: `failed to lookup address information: Name or service not known`.
- Cause: Missing core infrastructure services (Redis, DB, Kafka) - services try to connect but can't find dependencies.
- Fix: Start all core infra first: `docker compose -f docker-compose.dev-full.yml up -d db redis zookeeper kafka clickhouse objectstorage`

3) `feature-flags` restart loop (GeoIP DB)
- Cause: service expects `MAXMIND_DB_PATH=/share/GeoLite2-City.mmdb` mounted from repo `./share`.
- Fix (quick): fetch DB into `posthog/share/GeoLite2-City.mmdb`:

```bash
docker run --rm -v "$PWD/share:/out" debian:bookworm-slim \
  sh -lc "apt-get update && apt-get install -y curl brotli >/dev/null && \
  curl -s -L https://mmdbcdn.posthog.net/ --http1.1 | brotli -d > /out/GeoLite2-City.mmdb && \
  chmod 644 /out/GeoLite2-City.mmdb"
```

4) Migrations error: `ModuleNotFoundError: django_linear_migrations`
- Cause: `DEBUG=1` adds `django_linear_migrations` to `INSTALLED_APPS`, but the container doesn't ship dev deps.
- Fix: run migrations with `DEBUG=0` and a non‑default `SECRET_KEY` (see Quick Start step 3). Keep `web` in DEBUG=1 via override.

5) Proxy Caddyfile parse error: `invalid port '8000'': strconv.Atoi ...` 
- Cause: default `CADDY_HOST` rendered with quotes in the generated Caddyfile (`'http://localhost:8000'`).
- Fix: override `CADDYFILE` completely (host‑agnostic `:8000`), or set `CADDY_HOST` without quotes.

6) Banner: "dangerously running in PRODUCTION mode without TLS"
- Cause: `DEBUG=0` over HTTP triggers client-side JavaScript warning in `posthog/templates/overlays.html`.
- Fix: Set `E2E_TESTING=true` environment variable to disable the client-side TLS warning (see `docker-compose.debug-off.yml`).
- Note: The warning is generated by JavaScript that checks `location.protocol !== 'https:'` when not in debug or e2e testing mode.

## Validating Locally

Internal checks from the compose network (useful for debugging):

```bash
# Proxy health and login
docker run --rm --network posthog_default curlimages/curl:8.12.1 -sS http://proxy:8000/_health
docker run --rm --network posthog_default curlimages/curl:8.12.1 -sS -L http://proxy:8000/ | head

# Web health
docker run --rm --network posthog_default curlimages/curl:8.12.1 -sS http://web:8000/_health
```

## VM Access (GCP) and Firewall

- Script in `~`: `open_posthog_ports.sh` (created by us) to open ports to a given IP.
  - Default project/instance: `andrewm4894` / `posthog-dev`. Zone can be passed as arg 3.
  - Example: `./open_posthog_ports.sh 212.129.78.56/32 8010 us-central1-b`
  - Prints the VM external IP and sample URLs.

- Manual Cloud Shell sequence (if preferred):

```bash
export PROJECT_ID="andrewm4894"
export ZONE="us-central1-b"
export INSTANCE="posthog-dev"
export SOURCE_IP="212.129.78.56/32"
export TAG="posthog-dev"
gcloud config set project "$PROJECT_ID"
gcloud compute instances add-tags "$INSTANCE" --zone="$ZONE" --tags="$TAG"
export NETWORK=$(gcloud compute instances describe "$INSTANCE" --zone="$ZONE" --format='value(networkInterfaces[0].network.basename())')
gcloud compute firewall-rules create posthog-allow-8010 \
  --network="$NETWORK" --direction=INGRESS --priority=1000 --action=ALLOW \
  --rules=tcp:8010 --source-ranges="$SOURCE_IP" --target-tags="$TAG"
export EXT_IP=$(gcloud compute instances describe "$INSTANCE" --zone="$ZONE" --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
echo "Open: http://$EXT_IP:8010"
```

## Extras

- Start plugin server:

```bash
docker compose -f docker-compose.dev-full.yml up -d plugins
```

- Kafka UI:

```bash
docker compose -f docker-compose.dev-full.yml up -d kafka_ui
# then open http://localhost:9093
```

## Useful Logs

- Compose: `docker compose -f docker-compose.dev-full.yml logs -f <service>`
- App logs we captured: `~/compose_up.log`, `~/compose_migrate.log`

## Common One‑Liners

```bash
# Recreate proxy with our Caddyfile override
docker compose -f docker-compose.dev-full.yml -f docker-compose.debug-off.yml -f docker-compose.proxy-caddyfile.yml up -d --force-recreate proxy

# Recreate web with DEBUG=1
docker compose -f docker-compose.dev-full.yml -f docker-compose.debug-off.yml up -d --force-recreate web

# Clean up Docker space (be careful)
docker image prune -af; docker builder prune -af
```

