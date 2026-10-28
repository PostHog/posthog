#!/usr/bin/env bun
import { run } from './cli'

process.exitCode = run(process.argv.slice(2), {
    stdout: (text) => {
        process.stdout.write(`${text}\n`)
    },
    stderr: (text) => {
        process.stderr.write(`${text}\n`)
    },
})
