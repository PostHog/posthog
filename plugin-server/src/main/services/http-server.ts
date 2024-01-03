import { createServer, IncomingMessage, Server, ServerResponse } from 'http'
import { DateTime } from 'luxon'
import { IngestionConsumer, KafkaJSIngestionConsumer } from 'main/ingestion-queues/kafka-queue'
import * as prometheus from 'prom-client'

import { status } from '../../utils/status'

prometheus.collectDefaultMetrics()
const v8Profiler = require('v8-profiler-next')
v8Profiler.setGenerateType(1)

export function createHttpServer(
    port: number,
    healthChecks: { [service: string]: () => Promise<boolean> | boolean },
    analyticsEventsIngestionConsumer?: KafkaJSIngestionConsumer | IngestionConsumer
): Server {
    const server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
        if (req.method !== 'GET') {
            res.statusCode = 404
            res.end()
            return
        }
        if (req.url === '/_health') {
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
                // Note that we do not use `Promise.allSettled` here so we can
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
                status.info('💔', 'Server liveness check failed', checkResultsMapping)
            }

            res.end(JSON.stringify({ status: statusCode === 200 ? 'ok' : 'error', checks: checkResultsMapping }))
        } else if (req.url === '/_ready') {
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
        } else if (req.url === '/_metrics' || req.url === '/metrics') {
            prometheus.register
                .metrics()
                .then((metrics) => {
                    res.end(metrics)
                })
                .catch((err) => {
                    status.error('🩺', 'Error while collecting metrics', { err })
                    res.statusCode = 500
                    res.end()
                })
        } else if (req.url!.startsWith('/_profile/')) {
            try {
                exportProfile(req, res)
            } catch (err) {
                status.error('🩺', 'Error while collecting profile', { err })
                res.statusCode = 500
                res.end()
            }
        } else {
            res.statusCode = 404
            res.end()
        }
    })

    server.listen(port, () => {
        status.info('🩺', `Status server listening on port ${port}`)
    })

    return server
}

function exportProfile(req: IncomingMessage, res: ServerResponse) {
    // Mirrors golang's pprof behaviour of exposing ad-hoc profiles through HTTP endpoints
    // Port-forward pod 6738 on a target pod and run:
    //       curl -vOJ "http://localhost:6738/_profile/cpu"
    //   or  curl -vOJ "http://localhost:6738/_profile/heap?seconds=30"
    // The output can be loaded in the chrome devtools, in the Memory or Javascript profiler tabs.

    const url = new URL(req.url!, `http://${req.headers.host}`)
    const type = url.pathname.split('/').pop() ?? 'unknown'
    const durationSeconds = url.searchParams.get('seconds') ? parseInt(url.searchParams.get('seconds')!) : 30

    const sendHeaders = function (extension: string) {
        const fileName = `${type}-${DateTime.now().toUTC().toFormat('yyyyMMdd-HHmmss')}.${extension}`
        res.setHeader('Content-Disposition', `attachment; filename="${fileName}"`)
        res.setHeader('Profile-Type', type)
        res.setHeader('Profile-Duration-Seconds', durationSeconds)
        res.flushHeaders()
    }

    status.info('🩺', `Collecting ${type} profile...`)

    switch (type) {
        case 'cpu':
            sendHeaders('cpuprofile')
            v8Profiler.startProfiling('cpu', true)
            setTimeout(() => {
                outputProfileResult(res, type, v8Profiler.stopProfiling('cpu'))
            }, durationSeconds * 1000)
            break
        case 'heap':
            // Additional params for sampling heap profile, higher precision means bigger profile.
            // Defaults are taken from https://v8.github.io/api/head/classv8_1_1HeapProfiler.html
            const interval = url.searchParams.get('interval') ? parseInt(url.searchParams.get('interval')!) : 512 * 1024
            const depth = url.searchParams.get('depth') ? parseInt(url.searchParams.get('depth')!) : 16

            sendHeaders('heapprofile')
            v8Profiler.startSamplingHeapProfiling(interval, depth)
            setTimeout(() => {
                outputProfileResult(res, type, v8Profiler.stopSamplingHeapProfiling())
            }, durationSeconds * 1000)
            break
        default:
            res.statusCode = 404
            res.end()
    }
}

function outputProfileResult(res: ServerResponse, type: string, output: any) {
    status.info('🩺', `${type} profile collected, sending to client`)
    output.export(function (error: any, result: any) {
        if (error) {
            status.error('😖', 'Error while exporting profile', { error })
            res.statusCode = 500
            res.end()
        } else {
            res.end(result)
            output.delete?.() // heap profiles do not implement delete
        }
    })
    status.info('🩺', `${type} profile successfully exported`)
}
