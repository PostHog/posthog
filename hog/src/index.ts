#!/usr/bin/env -S bun --no-env-file
import { hasPendingSecretCalls, processRuntime } from '@/core/runtime'

import { run } from './cli'

// A promise chain rather than top-level await, which `bun build --bytecode` does not support.
void run(process.argv.slice(2), processRuntime()).then((code) => {
    process.exitCode = code
    if (hasPendingSecretCalls()) {
        // A keychain call that timed out still waits on its dialog. Exit once stdout drains, so an
        // agent isn't left waiting on a person.
        process.stdout.write('', () => process.exit(code))
    }
})
