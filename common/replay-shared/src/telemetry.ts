export interface ReplayTelemetry {
    capture(event: string, properties?: Record<string, unknown>): void
    captureException(error: Error, properties?: Record<string, unknown>): void
}

export const noOpTelemetry: ReplayTelemetry = {
    capture: () => {},
    captureException: () => {},
}
