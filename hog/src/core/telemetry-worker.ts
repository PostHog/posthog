import { parseJsonOrUndefined } from './json'
import { postBatch, SEND_TIMEOUT_MS, TelemetryBatch } from './telemetry'

// `index.ts` checks for this before parsing the command line, so no command may take this name.
export const TELEMETRY_WORKER_ARG = 'telemetry-worker'

export async function runTelemetryWorker(): Promise<void> {
    setTimeout(() => process.exit(0), SEND_TIMEOUT_MS + 1000).unref()
    try {
        const body = await new Response(Bun.stdin.stream()).text()
        if (parseJsonOrUndefined(body, TelemetryBatch) !== undefined) {
            await postBatch(fetch, body)
        }
    } catch {
        // No retry, so a worker never outlives its timeout.
    }
    process.exit(0)
}
