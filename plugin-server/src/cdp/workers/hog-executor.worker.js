const { exec } = require('@posthog/hogvm')
const crypto = require('crypto')
const RE2 = require('re2')

module.exports = function execBehavioralActionWorker(task) {
    const { bytecode, filterGlobals } = task
    const now = performance.now()
    let execResult
    let error
    let matched = false

    try {
        execResult = exec(bytecode, {
            timeout: 30000,
            maxAsyncSteps: 0,
            globals: filterGlobals,
            telemetry: false,
            external: {
                regex: { match: (regex, str) => new RE2(regex).test(str) },
                crypto,
            },
        })

        if (execResult && !execResult.error) {
            matched = typeof execResult.result === 'boolean' && execResult.result
        }
    } catch (e) {
        error = e
    }

    return {
        execResult,
        error,
        durationMs: performance.now() - now,
        matched,
    }
}
