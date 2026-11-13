import { z } from 'zod'

import { parseJsonOrUndefined } from './json'
import { SEND_TIMEOUT_MS, TELEMETRY_BATCH_URL } from './telemetry'

// The first argument that turns a hog process into the worker. `index.ts` checks it before hog
// parses the command line, so the worker skips config, credentials and its own usage event, and it
// never shows in `hog commands` or the help. No command in `commands/index.ts` may take this name.
export const TELEMETRY_WORKER_ARG = 'telemetry-worker'

// The parent built the batch, so the worker only checks that stdin holds one and sends it as is.
const Batch = z.object({ api_key: z.string(), batch: z.array(z.unknown()).min(1) })

// Runs in the detached process that `Runtime.sendTelemetryInBackground` starts. Nobody waits for
// it and nobody reads its output, so it never prints, and it exits on its own if the network hangs.
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
        // Lost events are not worth a retry that keeps a process around.
    }
    process.exit(0)
}
