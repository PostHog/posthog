import { logger } from '../../../utils/logger'
import { Component, ComponentMap } from './component'

/** Pluggable "boot/teardown" implementation behind the scope's state machine. */
export interface Runner {
    start(): Promise<void>
    stop(): Promise<void>
}

/**
 * Boots and tears down the map of components. They start in parallel, so
 * order is irrelevant; `stop` tears down only the ones that started.
 */
export class ComponentRunner<S extends Record<string, object>> implements Runner {
    private started: Array<{ name: string; value: object; stop: () => Promise<void> }> = []
    private containerCache?: S

    constructor(
        private readonly scopeName: string,
        private readonly components: ComponentMap<S>
    ) {}

    async start(): Promise<void> {
        const entries: Array<[string, Component<object>]> = Object.entries(this.components)
        logger.info(`Scope[${this.scopeName}]: starting ${entries.length} entries in parallel`)

        const results = await Promise.allSettled(
            entries.map(async ([name, component]) => {
                logger.info(`Scope[${this.scopeName}]: starting ${name}`)
                return await component.start()
            })
        )

        const started: Array<{ name: string; value: object; stop: () => Promise<void> }> = []
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
            for (let i = started.length - 1; i >= 0; i--) {
                try {
                    await started[i].stop()
                } catch (rollbackErr) {
                    logger.error(`Scope[${this.scopeName}]: ${started[i].name} stop failed during rollback`, {
                        error: rollbackErr,
                    })
                }
            }
            throw failures[0].error
        }

        this.started = started
        // `components` is typed `ComponentMap<S>`, so each entry's value is the
        // `S[K]` for its key — the assembled record is therefore `S`. The
        // assertion only bridges `Object.fromEntries` erasing per-key types.
        this.containerCache = Object.fromEntries(started.map((s) => [s.name, s.value])) as S
    }

    async stop(): Promise<void> {
        const entries = this.started
        this.started = []
        this.containerCache = undefined
        for (let i = entries.length - 1; i >= 0; i--) {
            logger.info(`Scope[${this.scopeName}]: stopping ${entries[i].name}`)
            try {
                await entries[i].stop()
            } catch (err) {
                logger.error(`Scope[${this.scopeName}]: ${entries[i].name} stop failed`, { error: err })
                throw err
            }
        }
    }

    getContainer(): S {
        if (!this.containerCache) {
            throw new Error('scope not started')
        }
        return this.containerCache
    }
}
