import { logger } from '../../../utils/logger'
import { Component, ComponentMap, Started } from './component'

/**
 * A `Component` whose value is the assembled container. It boots every
 * entry's component in parallel (order is irrelevant), and its `stop`
 * tears down only the ones that started, in reverse. If any entry fails
 * to start, the already-started ones are rolled back and the first error
 * is rethrown.
 */
export class ComponentRunner<S extends Record<string, object>> implements Component<S> {
    constructor(
        private readonly scopeName: string,
        private readonly components: ComponentMap<S>
    ) {}

    async start(): Promise<Started<S>> {
        const entries: Array<[string, Component<object>]> = Object.entries(this.components)
        logger.info(`Scope[${this.scopeName}]: starting ${entries.length} entries in parallel`)

        const results = await Promise.allSettled(
            entries.map(async ([name, component]) => {
                logger.info(`Scope[${this.scopeName}]: starting ${name}`)
                return await component.start()
            })
        )

        const started: Array<Started<object> & { name: string }> = []
        const failures: Array<{ name: string; error: unknown }> = []

        for (let i = 0; i < results.length; i++) {
            const result = results[i]
            const name = entries[i][0]
            if (result.status === 'fulfilled') {
                started.push({ name, value: result.value.value, stop: result.value.stop })
            } else {
                failures.push({ name, error: result.reason })
            }
        }

        if (failures.length > 0) {
            for (const f of failures) {
                logger.error(`Scope[${this.scopeName}]: ${f.name} start failed`, { error: f.error })
            }
            logger.error(`Scope[${this.scopeName}]: start failed, rolling back ${started.length} started value(s)`)
            await this.teardown(started)
            throw failures[0].error
        }

        // `components` is typed `ComponentMap<S>`, so each entry's value is the
        // `S[K]` for its key — the assembled record is therefore `S`. The
        // assertion only bridges `Object.fromEntries` erasing per-key types.
        const value = Object.fromEntries(started.map((s) => [s.name, s.value])) as S
        return { value, stop: () => this.teardown(started) }
    }

    private async teardown(started: Array<{ name: string; stop: () => Promise<void> }>): Promise<void> {
        for (let i = started.length - 1; i >= 0; i--) {
            logger.info(`Scope[${this.scopeName}]: stopping ${started[i].name}`)
            try {
                await started[i].stop()
            } catch (err) {
                logger.error(`Scope[${this.scopeName}]: ${started[i].name} stop failed`, { error: err })
                throw err
            }
        }
    }
}
