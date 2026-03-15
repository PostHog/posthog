import { Runtime } from '@temporalio/worker'
import { NativeConnection, Worker } from '@temporalio/worker'
import * as fs from 'fs/promises'

import { createActivities } from './activities'
import { BrowserPool } from './browser-pool'
import { EncryptionCodec } from './codec'
import { config } from './config'
import { createLogger } from './logger'
import { loadPlayerHtml } from './recorder'

const log = createLogger()

// Route Temporal SDK logs through our JSON logger so all output is structured.
Runtime.install({
    logger: {
        log: (level, message, meta) => {
            const { sdkComponent, taskQueue, ...rest } = meta ?? {}
            const fields = { ...rest, sdk_component: sdkComponent, task_queue: taskQueue }
            switch (level) {
                case 'TRACE':
                case 'DEBUG':
                    log.debug(fields, message)
                    break
                case 'INFO':
                    log.info(fields, message)
                    break
                case 'WARN':
                    log.warn(fields, message)
                    break
                case 'ERROR':
                    log.error(fields, message)
                    break
            }
        },
        trace: (message, meta) => log.debug(meta ?? {}, message),
        debug: (message, meta) => log.debug(meta ?? {}, message),
        info: (message, meta) => log.info(meta ?? {}, message),
        warn: (message, meta) => log.warn(meta ?? {}, message),
        error: (message, meta) => log.error(meta ?? {}, message),
    },
})

async function buildTLSConfig() {
    const { temporalClientRootCA, temporalClientCert, temporalClientKey } = config

    if (!temporalClientRootCA && !temporalClientCert && !temporalClientKey) {
        return undefined
    }
    if (!temporalClientRootCA || !temporalClientCert || !temporalClientKey) {
        throw new Error(
            'Partial TLS configuration: all three of TEMPORAL_CLIENT_ROOT_CA, TEMPORAL_CLIENT_CERT, and TEMPORAL_CLIENT_KEY must be set'
        )
    }

    let systemCAs = Buffer.alloc(0)
    try {
        systemCAs = await fs.readFile('/etc/ssl/certs/ca-certificates.crt')
    } catch {
        // System CA bundle not found, using only provided root CA
    }

    const combinedCA = Buffer.concat([systemCAs, Buffer.from(temporalClientRootCA)])

    return {
        serverRootCACertificate: combinedCA,
        clientCertPair: {
            crt: Buffer.from(temporalClientCert),
            key: Buffer.from(temporalClientKey),
        },
    }
}

async function main(): Promise<void> {
    const address = `${config.temporalHost}:${config.temporalPort}`
    const tls = await buildTLSConfig()

    const connection = await NativeConnection.connect({ address, tls })
    log.info({ address }, 'connected to temporal')

    const pool = new BrowserPool()
    await pool.launch()

    log.info('browser pool launched')

    await loadPlayerHtml()
    log.info({ path: config.playerHtmlPath }, 'player html loaded')

    const worker = Worker.create({
        connection,
        namespace: config.temporalNamespace,
        taskQueue: config.taskQueue,
        activities: createActivities(pool),
        maxConcurrentActivityTaskExecutions: config.maxConcurrentActivities,
        dataConverter: config.secretKey ? { payloadCodecs: [new EncryptionCodec(config.secretKey)] } : undefined,
    })

    const runningWorker = await worker

    const shutdown = () => {
        log.info('shutting down')
        runningWorker.shutdown()
    }

    process.on('SIGTERM', shutdown)
    process.on('SIGINT', shutdown)

    log.info({ task_queue: config.taskQueue }, 'worker started')
    await runningWorker.run()

    // run() resolves after shutdown drains all in-flight activities
    await pool.shutdown()
}

main().catch((err) => {
    log.error({ error: err instanceof Error ? err.message : String(err) }, 'worker failed to start')
    process.exit(1)
})
