import { createServer, IncomingMessage, Server, ServerResponse } from 'http'
import { IngestionConsumer } from 'main/ingestion-queues/kafka-queue'
import * as prometheus from 'prom-client'

import { status } from '../../utils/status'

export const HTTP_SERVER_PORT = 6738

prometheus.collectDefaultMetrics()

export function createHttpServer(
    healthChecks: { [service: string]: () => Promise<boolean> },
    analyticsEventsIngestionConsumer?: IngestionConsumer
): Server {
    const server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
        if (req.url === '/_health' && req.method === 'GET') {
            // Check that all health checks pass. Note that a failure of these
            // _may_ result in the process being terminated by e.g. Kubernetes
            // so the stakes are high.
            //
            // Also, Kubernetes will call this endpoint frequently, on each pod,
            // so we want to make sure it's fast and doesn't put any stress on
            // other services. Ideally it shouldn't make any calls to other
            // services.
            //
            // Here we take all of the health checks we are given, run them in
            // parallel, and return the results. If any of the checks fail, we
            // return a 503 status code, otherwise we return a 200 status code.
            //
            // In all cases we should return a JSON object with the following
            // structure:
            //
            // {
            //   "status": "ok" | "error",
            //   "checks": {
            //     "service1": "ok" | "error",
            //     "service2": "ok" | "error",
            //     ...
            //   }
            // }
            const checkResults = await Promise.all(
                // Note that we do not ues `Promise.allSettled` here so we can
                // assume that all promises have resolved. If there was a
                // rejected promise, the http server should catch it and return
                // a 500 status code.
                Object.entries(healthChecks).map(async ([service, check]) => {
                    try {
                        return { service, status: (await check()) ? 'ok' : 'error' }
                    } catch (error) {
                        return { service, status: 'error', error: error.message }
                    }
                })
            )

            const statusCode = checkResults.every((result) => result.status === 'ok') ? 200 : 503

            const checkResultsMapping = Object.fromEntries(
                checkResults.map((result) => [result.service, result.status])
            )

            res.statusCode = statusCode

            if (statusCode === 200) {
                status.info('💚', 'Server liveness check succeeded')
            } else {
                status.info('💔', 'Server liveness check failed', checkResults)
            }

            res.end(JSON.stringify({ status: statusCode === 200 ? 'ok' : 'error', checks: checkResultsMapping }))
        } else if (req.url === '/_ready' && req.method === 'GET') {
            // Check that, if the server should have a kafka queue,
            // the Kafka consumer is ready to consume messages
            if (!analyticsEventsIngestionConsumer || analyticsEventsIngestionConsumer.consumerReady) {
                status.info('💚', 'Server readiness check succeeded')
                const responseBody = {
                    status: 'ok',
                }
                res.statusCode = 200
                res.end(JSON.stringify(responseBody))
            } else {
                status.info('💔', 'Server readiness check failed')
                const responseBody = {
                    status: 'error',
                }
                res.statusCode = 503
                res.end(JSON.stringify(responseBody))
            }
        } else if (req.url === '/_metrics' && req.method === 'GET') {
            // Return prometheus metrics for this process.
            //
            // NOTE: we do not currently support gathering metrics from forked
            // processes e.g. those recorded in Piscina Workers. This is because
            // it may well be better to simply remove Piscina workers.
            //
            // See
            // https://github.com/siimon/prom-client/blob/master/example/cluster.js
            // for an example of how to gather metrics from forked processes.

            prometheus.register
                .metrics()
                .then((metrics) => {
                    res.end(metrics)
                })
                .catch((err) => {
                    status.error('🩺', 'Error while collecting metrics', err)
                    res.statusCode = 500
                    res.end()
                })
        } else {
            res.statusCode = 404
            res.end()
        }
    })

    server.listen(HTTP_SERVER_PORT, () => {
        status.info('🩺', `Status server listening on port ${HTTP_SERVER_PORT}`)
    })

    return server
}
