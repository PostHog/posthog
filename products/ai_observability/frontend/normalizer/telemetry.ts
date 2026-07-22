// Telemetry sink for the recipe normalizer. Kept injectable so the normalizer
// stays portable to Node (MCP server, tasks sandbox) — the browser wires a
// `posthog.capture` callback via `setNormalizerTelemetry`; elsewhere it's a noop.

type NormalizerTelemetryCallback = (event: string, properties: Record<string, unknown>) => void

let telemetryCallback: NormalizerTelemetryCallback = () => {}

export function setNormalizerTelemetry(callback: NormalizerTelemetryCallback): void {
    telemetryCallback = callback
}

export function emitNormalizerTelemetry(event: string, properties: Record<string, unknown>): void {
    telemetryCallback(event, properties)
}
