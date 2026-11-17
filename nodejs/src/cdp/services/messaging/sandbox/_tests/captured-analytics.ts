import type { EventMessage } from 'posthog-node'

import type { PostgresRouter } from '~/common/utils/db/postgres'

import type { SandboxEmailEvents } from '../sandbox-email-events'

export const capturedAnalytics: EventMessage[] = []

class InMemoryPostHog {
    disable(): Promise<void> {
        return Promise.resolve()
    }

    register(): Promise<void> {
        return Promise.resolve()
    }

    capture(message: EventMessage): void {
        capturedAnalytics.push(message)
    }

    captureException(): void {}

    flush(): Promise<void> {
        return Promise.resolve()
    }

    shutdown(): Promise<void> {
        return Promise.resolve()
    }
}

export function sandboxEventsCapturedInMemory(postgres: PostgresRouter): SandboxEmailEvents {
    let events: SandboxEmailEvents | undefined
    jest.isolateModules(() => {
        jest.doMock('posthog-node', () => ({ PostHog: InMemoryPostHog }))
        jest.requireActual<typeof import('~/common/config/config')>(
            '~/common/config/config'
        ).defaultConfig.POSTHOG_API_KEY = 'phc_sandbox_analytics_test'
        const { TeamManager } =
            jest.requireActual<typeof import('~/common/utils/team-manager')>('~/common/utils/team-manager')
        const { SandboxEmailEvents } =
            jest.requireActual<typeof import('../sandbox-email-events')>('../sandbox-email-events')
        events = new SandboxEmailEvents(new TeamManager(postgres))
    })
    jest.dontMock('posthog-node')
    return events!
}
