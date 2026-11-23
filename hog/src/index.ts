#!/usr/bin/env -S bun --no-env-file
import { hasPendingSecretCalls, processRuntime, STACK_WORKER_ARG } from '@/core/runtime'
import { runTelemetryWorker, TELEMETRY_WORKER_ARG } from '@/core/telemetry-worker'

import { run } from './cli'

// Internal workers bypass command startup so they never check for updates or send a usage event.
if (process.argv[2] === TELEMETRY_WORKER_ARG) {
    void runTelemetryWorker()
} else if (process.argv[2] === STACK_WORKER_ARG && process.send) {
    process.once('message', (request: unknown) => {
        void import('@/stack/worker').then(({ runStackWorker }) => runStackWorker(request, processRuntime()))
    })
    process.send({ ready: true })
} else {
    // A promise chain rather than top-level await, which `bun build --bytecode` does not support.
    void run(process.argv.slice(2), processRuntime()).then((code) => {
        process.exitCode = code
        if (hasPendingSecretCalls()) {
            // A keychain call that timed out still waits on its dialog. Exit once stdout drains, so an
            // agent isn't left waiting on a person.
            process.stdout.write('', () => process.exit(code))
        }
    })
}
