# Metrics dev bridge — charts fixes (INFRA-A follow-up)

Companion to [`deployment-layout.md`](./deployment-layout.md) and [`dashboard-mvp.md`](./dashboard-mvp.md).

INFRA-A (charts #11808) wired the dev metrics bridge (vmagent remote-write → otel-collector → capture-logs → metrics1)
but it (a) crash-looped the shared otel-collector daemonset and (b) never delivered a single metric.
Two root causes → two charts changes. This is the record, plus the ArgoCD experiment used to validate before the PR.

**Status:** the remote-write bridge (#11808) was **reverted** (#12233) and its follow-ups closed (#12235, INFRA-C #12021, prod-bridge #12020). The replacement is a dedicated **scrape** collector: **[charts#12239](https://github.com/PostHog/charts/pull/12239)** (dev, open) and **[charts#12248](https://github.com/PostHog/charts/pull/12248)** (prod-us/eu, draft, stacked on the dev PR). The remote-write diagnosis below is kept as the record of why.

## Symptoms

- `otel-collector-dev` daemonset: Degraded pods climbing (this is the **shared** logs/traces/metrics collector).
- WarpStream `vcn_metrics_dev`: 0 throughput.
- `posthog.metrics` (metrics1): 0 rows.

## Root cause 1 — collector image predates the receiver

The bridge adds a `prometheusremotewrite` receiver. That receiver was only promoted to alpha (and compiled into the
released contrib image) in **v0.131.0**. The daemonset runs `opentelemetry-collector-contrib:0.127.0`, so the config
fails to decode at startup:

```text
error decoding 'receivers': unknown type: "prometheusremotewrite" ... (valid values: [... prometheus prometheus_simple ...])
```

→ exit 1 → CrashLoopBackOff. The config lives in the shared configmap, so as pods cycle into it they crash fleet-wide.

**Fix:** pin the collector image to `>= 0.131.0`.

## Root cause 2 — exporter posts into the Cognito auth proxy

`otlphttp/posthog-metrics.endpoint: https://app.dev.posthog.dev/i/` is the Cognito-ALB'd **app** host. POSTs get
302-redirected to the login page (which returns 200), so the Go HTTP client follows the redirect and the collector
reports the export as **successful** while capture-logs never receives the data — a silent black-hole. This is why the
`debug` exporter logs metrics happily and there are no export errors, yet nothing reaches Kafka.

The working local collector config (`otel-collector-config.dev.yaml`) proves the intended pattern: exporters talk to
capture-logs **directly by service name** (`http://capture-logs:4318`), never a public domain.

**Fix:** point the exporter at the in-cluster capture-logs Service. The collector is in namespace `otel`; capture-logs
is in `posthog` (cf. `bin/send-dev-metrics.sh` port-forward `-n posthog svc/capture-logs … :4318`), so use the
cross-namespace FQDN. otlphttp appends `/v1/metrics`.

> Note: the existing **traces/logs** `otlphttp` exporter uses the same `app.dev.posthog.dev/i/` host and has the same
> black-hole — it's just been masked because traces also export to `otlp/quickwit`. Worth fixing in the same pass.

## Charts changes — `argocd/otel-collector/values/values.dev.yaml`

```yaml
# 1. Pin the image so the prometheusremotewrite receiver exists (file has no image: block today).
image:
  tag: '0.131.0'

# 2. Send to the in-cluster capture-logs Service, not the Cognito-protected app host.
config:
  exporters:
    otlphttp/posthog-metrics:
      endpoint: http://capture-logs.posthog.svc.cluster.local:4318 # was: https://app.dev.posthog.dev/i/
      tls:
        insecure: true # plain HTTP in-cluster
      headers:
        authorization: Bearer <dev-capture-token> # value stays in charts values, not duplicated in this public repo
      compression: gzip
      timeout: 10s
```

Both are required for end-to-end delivery: change 1 makes the fleet healthy and the bridge _receive_; change 2 makes the
metrics actually _arrive_.

## ArgoCD experiment (validate before the PR)

All doable in the ArgoCD UI (no kubectl needed). Turn **Auto-Sync OFF** on `otel-collector-dev` for the duration so it
doesn't revert live edits.

1. Edit the configmap `otel-collector-opentelemetry-collector-agent` (`relay.yaml`): set the `otlphttp/posthog-metrics`
   endpoint to `http://capture-logs.posthog.svc.cluster.local:4318` (+ `tls.insecure: true`).
2. Edit the **DaemonSet** `otel-collector-opentelemetry-collector-agent` → `spec.template.spec.containers[0].image` →
   `…/opentelemetry-collector-contrib:0.131.0`. This triggers the rollout; new pods come up on 0.131 reading the fixed
   configmap. (Rollout is `maxUnavailable: 10%`, so it rolls gradually.)
3. Verify:
   - Collector pod logs: `debug` exporter shows metrics; **no** otlphttp export errors.
   - WarpStream `vcn_metrics_dev`: throughput > 0.
   - `/metrics` SQL: `SELECT service_name, count(), max(timestamp) FROM posthog.metrics WHERE timestamp > now() - INTERVAL 1 HOUR GROUP BY 1`.

Re-enable Auto-Sync **after** the charts PR merges.

## Blocker (confirmed): vmagent RW v1 vs receiver RW v2

The vmagent → bridge link **cannot work as designed** — a hard protocol incompatibility, confirmed in vmagent's remote-write logs (the collector is reachable now; it just rejects every block):

```text
unexpected status code received after sending a block ... during retry #16: 415; response body="Unsupported proto version"; re-sending the block in ...
```

- The OTel `prometheusremotewrite` receiver supports **Prometheus Remote Write 2.0 only** (`io.prometheus.write.v2.Request`).
- vmagent (v1.97.1) sends **Remote Write 1.0** and has **no v2 support** (VictoriaMetrics open FR [#10413](https://github.com/VictoriaMetrics/VictoriaMetrics/issues/10413); they favor their zstd RW v1 over v2). There's also an open receiver bug rejecting remote-write-originated metrics ([contrib #41840](https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/41840)).
- So every block is `415`'d and retried forever — vmagent's queue for that URL grows (280–445 KB blocks, retry #16+). The `/api/v1/write` path was never the problem.

No values tweak fixes this. The collector-side fixes (image + endpoint) were still correct — they un-wedged the daemonset and fixed the black-hole endpoint — but the bridge can't receive vmagent's stream.

### Redesign options (the real long-term fix)

1. **Dedicated single-replica scrape collector** — a standalone otel-collector Deployment (not the daemonset) with a `prometheus` receiver that scrapes the dashboard targets via K8s SD, filters, and exports OTLP to capture-logs. Single replica → none of the daemonset N-duplication that made RW attractive originally. Pure OTel, no protocol issue. Tradeoff: re-scrapes targets (notably per-node cadvisor/node-exporter = extra kubelet load), needs SD RBAC.
2. **RW v1 → OTLP shim** — keep vmagent's single scrape; point its second remote-write at a component that accepts RW v1 and re-emits OTLP (e.g. Grafana Alloy `prometheus.receive_http`). Avoids re-scraping; adds a component to run.
3. **Wait for vmagent RW v2** (#10413) — no ETA; not viable now.

**Chosen: option 1**, built as the `metrics-bridge` ArgoCD app — [charts#12239](https://github.com/PostHog/charts/pull/12239) (dev) + [charts#12248](https://github.com/PostHog/charts/pull/12248) (prod draft). A single-replica deployment-mode collector that scrapes annotation-discovered targets (ingestion services, kminion, envoy, kube-state, argo-rollouts) → `filter/dashboard` → OTLP → capture-logs; per-node cadvisor/node-exporter (`container_*`/`node_*`/`kubelet_*`) deferred. Token handling: **dev** sets the capture token inline in `values.dev.yaml` (matching the otel-collector daemonset's otlphttp exporter); **prod** uses **external-secrets** (ExternalSecret via the chart's `extraManifests`, mirroring the otel-ingest gateway) — the per-region internal-infra token is seeded in AWS Secrets Manager as `metrics-bridge-token-secrets` / `CAPTURE_TOKEN` via the **`PostHog/secrets`** tool, then synced automatically (hourly). Prod is gated on the prod ingest plane + `metrics1` DDL + a dedicated internal-infra project per region. Full rollout runbook is in the #12248 description.

Meanwhile, stop the bleed: **remove the dead `:19291/api/v1/write` target from `argocd/vmagent/values/values.dev.yaml`** so vmagent stops retrying undeliverable blocks. (vmagent-dev has auto-sync on, so this only changes via a charts PR.)

## Open item — token → team

The bridge token maps to exactly one team. Local dev uses `phc_local` → team 1. If the bridge token isn't the token for
the project you're querying (the `/metrics` tab you're watching), the rows land on a different team and you won't see
them there even after both fixes. `deployment-layout.md`'s open decision is to send infra metrics to a dedicated
`posthog-internal-infra` project rather than the dogfood team (so they don't flip `team_has_metrics`). Decide which
before/with the PR.
