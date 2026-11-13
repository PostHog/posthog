import { z } from 'zod'

import { parseJsonOrUndefined } from './json'
import { SEND_TIMEOUT_MS, TELEMETRY_BATCH_URL } from './telemetry'

// `index.ts` checks for this argument before hog parses the command line, so the worker skips config,
// credentials and its own usage event. No command in `commands/index.ts` may take this name.
export const TELEMETRY_WORKER_ARG = 'telemetry-worker'

const Batch = z.object({ api_key: z.string(), batch: z.array(z.unknown()).min(1) })

export async function runTelemetryWorker(): Promise<void> {
    setTimeout(() => process.exit(0), SEND_TIMEOUT_MS + 1000).unref()
    try {
        const body = await new Response(Bun.stdin.stream()).text()
        if (parseJsonOrUndefined(body, Batch) !== undefined) {
            const response = await fetch(TELEMETRY_BATCH_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
            })
            await response.body?.cancel()
        }
    } catch {
        // No retry, so a worker never outlives its timeout.
    }
    process.exit(0)
}
