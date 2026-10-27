#!/usr/bin/env bun
import { run } from './cli'
import { processRuntime } from './core/runtime'

// A promise chain rather than top-level await, which `bun build --bytecode` does not support.
void run(process.argv.slice(2), processRuntime()).then((code) => {
    process.exitCode = code
})
