# OpenSearch — local LLM trace reverse index

Local Docker OpenSearch cluster + checked-in `llm-traces-v0_1` index template. Stage 0 of the LLMA reverse-index POC; the (forthcoming) `rust/opensearch-indexer` writes to `localhost:9201`. Prod uses managed AWS OpenSearch Service via Terraform in `posthog-cloud-infra`.

## What's running

| Service                 | Image                                            | Host port                 | Notes                                                       |
| ----------------------- | ------------------------------------------------ | ------------------------- | ----------------------------------------------------------- |
| `opensearch`            | `opensearchproject/opensearch:2.13.0`            | `127.0.0.1:9201` → `9200` | single-node, security plugin off, 512m heap, ephemeral data |
| `opensearch-dashboards` | `opensearchproject/opensearch-dashboards:2.13.0` | `127.0.0.1:5601` → `5601` | UI for ad-hoc queries                                       |
| `opensearch-init`       | `curlimages/curl:8.10.1`                         | —                         | one-shot bootstrap; exits 0 after applying template + alias |

Activated by the `opensearch_search` capability (in `ai_features` intent). Run via `bin/start ai_features`, or directly: `docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile opensearch up -d`.

## Verify

```bash
curl -s http://localhost:9201/_cluster/health         # status: green or yellow
curl -s 'http://localhost:9201/_cat/indices/llm-traces-v0_1-*?v'    # llm-traces-v0_1-000001
curl -s http://localhost:9201/_alias/llm-traces       # is_write_index: true
```

Dashboards UI: <http://localhost:5601> → Dev Tools → `GET llm-traces/_mapping`.

## Reset (wipe data, re-bootstrap)

```bash
docker compose -f docker-compose.dev.yml down -v opensearch opensearch-dashboards opensearch-init
docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile opensearch up -d
```

## Reapply template after editing the JSON

```bash
docker compose -f docker-compose.dev.yml run --rm opensearch-init
```

Idempotent — safe to run any time. Template applies to _new_ indices only; to pick up mapping changes on the existing backing index, do a full reset.

## Notes

- **`opensearch-init` shows `Exited (0)` in `docker ps -a`** — that's expected. It's a one-shot bootstrap container, not a daemon.
- **Port `9200` is owned by Temporal's Elasticsearch** — that's why OpenSearch publishes on `9201`.
- **No ISM locally.** Hot → UltraWarm requires UltraWarm-typed nodes (S3-backed); a single-node cluster can't provide them. Local is hot-only; prod uses ISM via Terraform.
- **Security plugin is off.** Bind is loopback-only (`127.0.0.1`) so the open cluster isn't reachable off-host. AWS OpenSearch Service authenticates via SigV4/IAM at the load balancer instead — no in-cluster RBAC there either.
- **Schema source of truth:** `llm-traces-v0_1.template.json`. Same file is consumed by the init container locally and (eventually) by Terraform in prod.
- **Local cluster status is yellow, not green.** Template sets `number_of_replicas: 1` for prod redundancy; the single-node local cluster can't allocate the replica, so the index sits in yellow. Functionally fine for dev.
