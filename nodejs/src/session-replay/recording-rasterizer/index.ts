import { NativeConnection, Worker } from '@temporalio/worker'
import * as fs from 'fs/promises'

import { rasterizeRecordingActivity, setBrowserPool } from './activities'
import { BrowserPool } from './browser-pool'
import { config } from './config'

async function buildTLSConfig() {
    const { temporalClientRootCA, temporalClientCert, temporalClientKey } = config

    if (!(temporalClientRootCA && temporalClientCert && temporalClientKey)) {
        return undefined
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
    const pool = new BrowserPool()
    await pool.launch()
    setBrowserPool(pool)

    console.log('Browser pool launched')

    const address = `${config.temporalHost}:${config.temporalPort}`
    const tls = await buildTLSConfig()

    const connection = await NativeConnection.connect({ address, tls })
    console.log(`Connected to Temporal at ${address}`)

    const worker = Worker.create({
        connection,
        namespace: config.temporalNamespace,
        taskQueue: config.taskQueue,
        activities: { 'rasterize-recording': rasterizeRecordingActivity },
        maxConcurrentActivityTaskExecutions: config.maxConcurrentActivities,
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
