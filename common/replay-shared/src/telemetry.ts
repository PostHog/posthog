export interface ReplayTelemetry {
    capture(event: string, properties?: Record<string, unknown>): void
    captureException(error: Error, properties?: Record<string, unknown>): void
    // Low-cardinality operational metric. Attribute values must stay a small fixed set — no ids or URLs.
    count?(name: string, attributes?: Record<string, string>): void
}

export const noOpTelemetry: ReplayTelemetry = {
    capture: () => {},
    captureException: () => {},
    count: () => {},
}
