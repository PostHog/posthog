#!/usr/bin/env -S bun --no-env-file
import { hasPendingSecretCalls, processRuntime } from '@/core/runtime'
import { runTelemetryWorker, TELEMETRY_WORKER_ARG } from '@/core/telemetry-worker'

import { run } from './cli'

// The binary runs in one of two ways. A person or agent runs hog commands, which the else branch
// handles. At the end of a run, hog also starts itself as `hog telemetry-worker` to send that run's
// telemetry in the background (see `sendTelemetryInBackground` in core/runtime.ts). That worker
// skips the command parser, so it loads no config, needs no credentials and sends no event of its own.
if (process.argv[2] === TELEMETRY_WORKER_ARG) {
    void runTelemetryWorker()
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
