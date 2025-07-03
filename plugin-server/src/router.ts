import express, { Request, Response } from 'express'
import { DateTime } from 'luxon'
import * as prometheus from 'prom-client'

import { PluginServerService } from '~/types'

import { logger } from './utils/logger'
import { delay } from './utils/utils'

prometheus.collectDefaultMetrics()
const v8Profiler = require('v8-profiler-next')
v8Profiler.setGenerateType(1)

export function setupCommonRoutes(
    app: express.Application,
    services: Pick<PluginServerService, 'id' | 'healthcheck'>[]
): express.Application {
    app.get('/_health', buildGetHealth(services))
    app.get('/_ready', buildGetHealth(services))
    app.get('/_metrics', getMetrics)
    app.get('/metrics', getMetrics)
    app.get('/_profile/:type', getProfileByType)

    return app
}

const buildGetHealth =
    (services: Pick<PluginServerService, 'id' | 'healthcheck'>[]) => async (req: Request, res: Response) => {
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
            services.map(async (service) => {
                try {
                    return { service: service.id, status: (await service.healthcheck()) ? 'ok' : 'error' }
                } catch (error) {
                    return { service: service.id, status: 'error', error: error.message }
                }
            })
        )

        const statusCode = checkResults.every((result) => result.status === 'ok') ? 200 : 503

        const checkResultsMapping = Object.fromEntries(checkResults.map((result) => [result.service, result.status]))

        if (statusCode === 200) {
            logger.info('💚', 'Server liveness check succeeded')
        } else {
            logger.error('💔', 'Server liveness check failed', { checkResults: checkResultsMapping })
        }

        return res.status(statusCode).json({ status: statusCode === 200 ? 'ok' : 'error', checks: checkResultsMapping })
    }

const getMetrics = async (req: Request, res: Response) => {
    try {
        const metrics = await prometheus.register.metrics()
        res.send(metrics)
    } catch (err) {
        logger.error('🩺', 'Error while collecting metrics', { err })
        res.sendStatus(500)
    }
}

async function getProfileByType(req: Request, res: Response) {
    try {
        // Mirrors golang's pprof behaviour of exposing ad-hoc profiles through HTTP endpoints
        // Port-forward pod 6738 on a target pod and run:
        //       curl -vOJ "http://localhost:6738/_profile/cpu"
        //   or  curl -vOJ "http://localhost:6738/_profile/heap?seconds=30"
        // The output can be loaded in the chrome devtools, in the Memory or Javascript profiler tabs.

        const type = req.params.type
        const durationSeconds = typeof req.query.seconds === 'string' ? parseInt(req.query.seconds) : 30
        const interval = typeof req.query.interval === 'string' ? parseInt(req.query.interval) : undefined

        const sendHeaders = function (extension: string) {
            const fileName = `${type}-${DateTime.now().toUTC().toFormat('yyyyMMdd-HHmmss')}.${extension}`

            res.header({
                'Content-Type': 'application/octet-stream',
                'Content-Disposition': `attachment; filename="${fileName}"`,
                'Profile-Type': type,
                'Profile-Duration-Seconds': durationSeconds,
            })
        }

        logger.info('🩺', `Collecting ${type} profile for ${durationSeconds} seconds...`)

        let finishProfile: (() => any) | undefined

        switch (type) {
            case 'cpu':
                // See https://v8docs.nodesource.com/node-18.16/d2/d34/classv8_1_1_cpu_profiler.html
                const mode = req.query.mode === '0' ? 0 : 1 // Default to 1 = kCallerLineNumbers
                v8Profiler.setSamplingInterval(interval ?? 1000) // in microseconds
                v8Profiler.startProfiling('cpu', true, mode)
                finishProfile = () => v8Profiler.stopProfiling('cpu')
                break
            case 'heap':
                // See https://v8docs.nodesource.com/node-18.16/d7/d76/classv8_1_1_heap_profiler.html
                const depth = typeof req.query.depth === 'string' ? parseInt(req.query.depth) : 16
                v8Profiler.startSamplingHeapProfiling(interval ?? 512 * 1024, depth)
                finishProfile = () => v8Profiler.stopSamplingHeapProfiling()
                break
        }

        if (finishProfile) {
            sendHeaders(`${type}profile`)
            await delay(durationSeconds * 1000)
            const output = finishProfile()

            const data = await new Promise((resolve, reject) => {
                output.export(function (error: any, result: any) {
                    if (error) {
                        reject(error)
                        logger.error('😖', 'Error while exporting profile', { error })
                    } else {
                        resolve(result)
                        output.delete?.() // heap profiles do not implement delete
                        logger.info('🩺', `${type} profile successfully exported`)
                    }
                })
            })

            return res.send(data)
        }

        return res.sendStatus(404)
    } catch (error) {
        logger.error('😖', 'Error while exporting profile', { error })
        res.sendStatus(500)
    }
}
