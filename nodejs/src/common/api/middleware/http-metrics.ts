import { Histogram } from 'prom-client'
import { NextFunction, Request, Response } from 'ultimate-express'

const EXCLUDED_PATHS = ['/_health', '/_ready', '/_metrics', '/metrics']

const httpRequestDuration = new Histogram({
    name: 'http_request_duration_seconds',
    help: 'Duration of HTTP requests in seconds',
    labelNames: ['method', 'route', 'status_code'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
})

export function httpMetricsMiddleware(req: Request, res: Response, next: NextFunction): void {
    if (EXCLUDED_PATHS.some((p) => req.path === p || req.path.startsWith(p + '/'))) {
        next()
        return
    }

    const start = performance.now()

    res.on('finish', () => {
        const duration = (performance.now() - start) / 1000
        // req.route is only set when Express matches a route handler.
        // Requests rejected by middleware (e.g. auth 401) also have no route,
        // so we distinguish them from genuine 404s via status code.
        const route = req.route?.path ?? (res.statusCode === 404 ? 'unmatched' : 'middleware_rejected')
        httpRequestDuration
            .labels({
                method: req.method,
                route,
                status_code: String(res.statusCode),
            })
            .observe(duration)
    })

    next()
}
