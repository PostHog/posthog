#!/usr/bin/env bun
import { run } from './program'
import { processRuntime } from './runtime'

process.exitCode = await run(process.argv.slice(2), processRuntime())
