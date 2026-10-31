#!/usr/bin/env -S bun --no-env-file
import { processRuntime } from '@/core/runtime'

import { run } from './cli'

// A promise chain rather than top-level await, which `bun build --bytecode` does not support.
void run(process.argv.slice(2), processRuntime()).then((code) => {
    process.exitCode = code
})
