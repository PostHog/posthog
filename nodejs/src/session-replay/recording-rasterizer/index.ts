import { NativeConnection, Worker } from '@temporalio/worker'
import * as fs from 'fs/promises'

import { rasterizeRecordingActivity, setBrowserPool } from './activities'
import { BrowserPool } from './browser-pool'
import { EncryptionCodec } from './codec'
import { config } from './config'
import { loadPlayerHtml } from './recorder'

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
    console.log(`Connected to Temporal at ${address}`)

    const pool = new BrowserPool()
    await pool.launch()
    setBrowserPool(pool)

    console.log('Browser pool launched')

    await loadPlayerHtml()
    console.log(`Player HTML loaded from ${config.playerHtmlPath}`)

    const worker = Worker.create({
        connection,
        namespace: config.temporalNamespace,
        taskQueue: config.taskQueue,
        activities: { 'rasterize-recording': rasterizeRecordingActivity },
        maxConcurrentActivityTaskExecutions: config.maxConcurrentActivities,
        dataConverter: config.secretKey ? { payloadCodecs: [new EncryptionCodec(config.secretKey)] } : undefined,
    })

    const runningWorker = await worker

    const shutdown = () => {
        console.log('Shutting down...')
        runningWorker.shutdown()
    }

    process.on('SIGTERM', shutdown)
    process.on('SIGINT', shutdown)

    console.log(`Worker started on queue "${config.taskQueue}"`)
    await runningWorker.run()

    // run() resolves after shutdown drains all in-flight activities
    await pool.shutdown()
}

main().catch((err) => {
    console.error('Worker failed to start:', err)
    process.exit(1)
})
