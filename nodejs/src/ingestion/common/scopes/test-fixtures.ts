import { Component } from '~/common/scopes/component'

export type TrackedComponent = Component<{ name: string }> & { startCalls: number; stopCalls: number }

/** A `Component` that appends `start:<name>`/`stop:<name>` to `log` and counts calls. */
export function makeComponent(name: string, log: string[]): TrackedComponent {
    const component: TrackedComponent = {
        startCalls: 0,
        stopCalls: 0,
        start: jest.fn(() => {
            component.startCalls++
            log.push(`start:${name}`)
            return Promise.resolve({
                value: { name },
                stop: (): Promise<void> => {
                    component.stopCalls++
                    log.push(`stop:${name}`)
                    return Promise.resolve()
                },
            })
        }),
    }
    return component
}
