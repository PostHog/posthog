#!/usr/bin/env node
/*
 * Long-running host process that keeps the container alive between
 * dispatches. Dispatches themselves go through `docker exec node
 * /sandbox/dispatch.js ...` (see DockerSandbox.invoke in v2 shared), so this
 * process's only job today is to stay running and respond to a graceful
 * shutdown signal.
 *
 * Future: we may switch to a long-lived JSON-RPC over a Unix socket once
 * per-exec startup cost shows up in benchmarks. For now `docker exec` is the
 * simpler integration and lets the dispatcher stay a pure stdin/stdout
 * pipeline.
 *
 * Health: writes /workdir/host.alive on boot. The runner-side pool checks
 * for that file before declaring the sandbox ready.
 */

'use strict'

const fs = require('node:fs')
const path = require('node:path')

const WORKDIR = process.env.SANDBOX_WORKDIR || '/workdir'

function writeAliveMarker() {
    try {
        fs.mkdirSync(WORKDIR, { recursive: true })
        fs.writeFileSync(path.join(WORKDIR, 'host.alive'), String(process.pid))
    } catch (err) {
        process.stderr.write(`host: failed to write alive marker: ${err.message}\n`)
        process.exit(1)
    }
}

function setupShutdown() {
    const stop = (sig) => {
        process.stderr.write(`host: ${sig} received, exiting\n`)
        try {
            fs.unlinkSync(path.join(WORKDIR, 'host.alive'))
        } catch {
            /* best effort */
        }
        process.exit(0)
    }
    process.on('SIGTERM', () => stop('SIGTERM'))
    process.on('SIGINT', () => stop('SIGINT'))
}

function main() {
    writeAliveMarker()
    setupShutdown()
    process.stdout.write(`host: alive, pid=${process.pid}, workdir=${WORKDIR}\n`)
    // Keep the event loop busy with a long-interval no-op so the process
    // doesn't exit prematurely. Cheap heartbeat for log aggregators.
    setInterval(() => {
        // intentionally empty
    }, 60_000).unref()
    // Re-arm the ref so the interval actually keeps us alive.
    // (Unref'd intervals don't, but we want this one to.)
    setInterval(() => {
        // intentionally empty — keeps process alive without spamming logs
    }, 60_000)
}

if (require.main === module) {
    main()
}

module.exports = { writeAliveMarker, setupShutdown }
