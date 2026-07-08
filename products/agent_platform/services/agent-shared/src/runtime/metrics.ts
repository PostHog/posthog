/**
 * Prometheus metrics surface for the agent-platform fleet.
 *
 * agent-shared historically dropped prom-client to stay lean (see the note in
 * `instrument.ts`). We add it back here — deliberately and in one place —
 * because the three deployable services (ingress, runner, janitor) all need a
 * uniform, scrapeable metrics surface for fleet dashboards + alerting.
 * prom-client is pure JS and bundles cleanly into each esbuild entrypoint; the
 * structured-log `instrument()` helper stays for ad-hoc latency tracing.
 *
 * Each service at boot:
 *   1. `initMetrics({ service })` once — sets a `service` default label (so
 *      every series, including the Node process defaults, is sliceable per
 *      service in a fleet dashboard) and registers default process metrics
 *      (CPU, RSS/heap, GC pauses, event-loop lag, open FDs).
 *   2. In prod, `createMetricsServer({ port, log })` on a DEDICATED port
 *      (default 6738, AGENT_METRICS_PORT) — never the public request port.
 *      vmagent scrapes the pod on this port; the internet-facing ingress
 *      listener never serves `/metrics`. The metrics server logs nothing per
 *      scrape. In LOCAL DEV the three services share a host, so binding the
 *      same dedicated port thrice collides — instead each mounts the
 *      `handleMetricsRequest` hook as a subpath on its own main/health server
 *      (distinct ports already), and no dedicated server is started. Prod
 *      behaviour (and the chart's scrape config) is unchanged.
 *
 * Express services additionally record `agent_http_request_duration_seconds`
 * via a tiny middleware (kept in each service so agent-shared stays
 * express-free) calling `recordHttpRequest(...)`, and keep `/healthz` +
 * `/metrics` out of their access log via `isMetricsExcludedPath`.
 *
 * Per-service metric definitions live in `<service>/src/metrics.ts`, declared
 * against the single shared `register` re-exported here.
 */

import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import { collectDefaultMetrics, Counter, Gauge, Histogram, register } from 'prom-client'

import type { Logger } from './logger'

// Re-export the metric classes + registry so services declare metrics without
// importing prom-client directly (keeps the dependency surface in one file).
export { Counter, Gauge, Histogram, register }

/**
 * Paths an access logger or the metrics server must never log per-request:
 * liveness probes and the scrape endpoint, which both fire on a fixed interval
 * and would otherwise drown the `info` stream.
 */
export const METRICS_EXCLUDED_PATHS = ['/healthz', '/_health', '/_ready', '/metrics', '/_metrics']

export function isMetricsExcludedPath(path: string): boolean {
    return METRICS_EXCLUDED_PATHS.some((p) => path === p || path.startsWith(`${p}/`))
}

let initialized = false

/**
 * One-time metrics init. Idempotent — `collectDefaultMetrics()` throws on a
 * second registration, so the guard makes a double-call (e.g. a test importing
 * two entrypoints) a no-op. Sets a `service` default label so a fleet-wide
 * query can do `{service="agent-runner"}` even before vmagent's namespace
 * relabeling is in play.
 */
export function initMetrics(opts: { service: string }): void {
    if (initialized) {
        return
    }
    initialized = true
    register.setDefaultLabels({ service: opts.service })
    collectDefaultMetrics()
}

/**
 * Server-side latency of inbound HTTP requests, shared by the express-based
 * services (ingress, janitor). The `route` label is the express route PATTERN
 * (`/:slug/chat/run`), never the resolved path, so per-agent slugs / session
 * ids can't blow up cardinality.
 */
export const httpRequestDuration = new Histogram({
    name: 'agent_http_request_duration_seconds',
    help: 'Duration of inbound HTTP requests handled by an agent service, by route + status.',
    labelNames: ['method', 'route', 'status_code'],
    buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
})

/** Record one completed HTTP request. Framework-agnostic so agent-shared keeps no express dep. */
export function recordHttpRequest(
    labels: { method: string; route: string; statusCode: number },
    durationSeconds: number
): void {
    httpRequestDuration
        .labels({ method: labels.method, route: labels.route, status_code: String(labels.statusCode) })
        .observe(durationSeconds)
}

/**
 * Serve `GET /metrics` + `GET /_metrics` (the chart's default scrape path) from
 * the shared registry. Returns true if it handled the request (path matched),
 * false otherwise — so the same logic backs both the dedicated prod server and
 * a same-port dev mount on an existing service server. Silent per request.
 */
export function handleMetricsRequest(req: IncomingMessage, res: ServerResponse, log: Logger): boolean {
    const path = (req.url ?? '/').split('?', 1)[0]
    if (req.method === 'GET' && (path === '/metrics' || path === '/_metrics')) {
        register
            .metrics()
            .then((body) => {
                res.writeHead(200, { 'content-type': register.contentType })
                res.end(body)
            })
            .catch((err: unknown) => {
                log.error({ err: err instanceof Error ? err.message : String(err) }, 'metrics.collect_failed')
                res.writeHead(500)
                res.end()
            })
        return true
    }
    return false
}

/**
 * Start the dedicated Prometheus scrape server (prod). Everything other than the
 * metrics paths 404s. Deliberately silent per request — scrapes fire every ~60s
 * and would otherwise flood the log. In dev, services skip this and mount
 * `handleMetricsRequest` on their main server instead (see the module note).
 */
export function createMetricsServer(opts: { port: number; log: Logger }): Server {
    const server = createServer((req, res) => {
        if (handleMetricsRequest(req, res, opts.log)) {
            return
        }
        res.writeHead(404)
        res.end()
    })
    server.listen(opts.port, () => opts.log.info({ port: opts.port }, 'metrics server listening'))
    return server
}
