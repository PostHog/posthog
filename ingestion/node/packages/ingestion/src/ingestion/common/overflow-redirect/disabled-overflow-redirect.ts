import { Component } from '~/ingestion/common/scopes'
import { HealthCheckResult, HealthCheckResultOk } from '~/types'

import { OverflowRedirectService } from './overflow-redirect-service'

/**
 * No-op overflow redirect for lanes where overflow is disabled. Never
 * redirects and holds no state, so callers can always depend on a service
 * being present instead of branching on `undefined`.
 */
export class DisabledOverflowRedirect implements OverflowRedirectService {
    handleEventBatch(): Promise<Set<string>> {
        return Promise.resolve(new Set())
    }

    healthCheck(): Promise<HealthCheckResult> {
        return Promise.resolve(new HealthCheckResultOk())
    }

    shutdown(): Promise<void> {
        return Promise.resolve()
    }
}

/** Scope component for the no-op overflow redirect (overflow disabled for the lane). */
export class DisabledOverflowRedirectComponent implements Component<OverflowRedirectService> {
    start(): Promise<{ value: OverflowRedirectService; stop: () => Promise<void> }> {
        const service = new DisabledOverflowRedirect()
        return Promise.resolve({ value: service, stop: () => service.shutdown() })
    }
}
