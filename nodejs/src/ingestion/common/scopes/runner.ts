import { logger } from '~/common/utils/logger'

import { Component, ComponentMap, Started } from './component'
import type { Startable } from './scope'

/**
 * A `Component` that runs a child layer on top of a parent scope. On
 * `start` it acquires the parent (refcounted), builds the child's component
 * map from the parent's container, boots those components in parallel, and
 * exposes `parent ∪ child`. If a child entry fails, the already-started
 * children are rolled back, the parent is released, and the first error is
 * rethrown. The returned `stop` tears children down in parallel, then
 * releases the parent. A root scope is this runner over an `EmptyScope`.
 */
export class ScopeRunner<SParent extends Record<string, object>, SChild extends Record<string, object>>
    implements Component<SParent & SChild>
{
    constructor(
        private readonly parent: Startable<SParent>,
        private readonly childComponents: (parentContainer: SParent) => ComponentMap<SChild>,
        private readonly name: string
    ) {}

    async start(): Promise<Started<SParent & SChild>> {
        const parentHandle = await this.parent.start()
        try {
            const children = await this.startChildren(parentHandle.container)
            return {
                value: { ...parentHandle.container, ...children.value },
                stop: async (): Promise<void> => {
                    try {
                        await children.stop()
                    } finally {
                        await parentHandle.stop()
                    }
                },
            }
        } catch (err) {
            try {
                await parentHandle.stop()
            } catch (parentStopErr) {
                logger.error(`Scope[${this.name}]: parent stop failed during rollback`, { error: parentStopErr })
            }
            throw err
        }
    }

    private async startChildren(parentContainer: SParent): Promise<Started<SChild>> {
        const components: ComponentMap<SChild> = this.childComponents(parentContainer)
        const entries: Array<[string, Component<object>]> = Object.entries(components)
        logger.info(`Scope[${this.name}]: starting ${entries.length} entries in parallel`)

        const results = await Promise.allSettled(
            entries.map(async ([name, component]) => {
                logger.info(`Scope[${this.name}]: starting ${name}`)
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
                logger.error(`Scope[${this.name}]: ${f.name} start failed`, { error: f.error })
            }
            logger.error(`Scope[${this.name}]: start failed, rolling back ${started.length} started value(s)`)
            // Keep the start failure as the primary cause; if rolling back the
            // partially-started scope also fails, fold those errors in rather
            // than dropping them or letting them mask the root cause.
            try {
                await this.teardown(started)
            } catch (rollbackErr) {
                const rollbackErrors = rollbackErr instanceof AggregateError ? rollbackErr.errors : [rollbackErr]
                throw new AggregateError(
                    [failures[0].error, ...rollbackErrors],
                    `Scope[${this.name}]: start failed and rollback teardown failed`
                )
            }
            throw failures[0].error
        }

        // `components` is typed `ComponentMap<SChild>`, so each entry's value
        // is the `SChild[K]` for its key — the assembled record is therefore
        // `SChild`. The assertion only bridges `Object.fromEntries` erasing
        // per-key types.
        const value = Object.fromEntries(started.map((s) => [s.name, s.value])) as SChild
        return { value, stop: () => this.teardown(started) }
    }

    private async teardown(started: Array<{ name: string; stop: () => Promise<void> }>): Promise<void> {
        // Siblings within a scope are built independently from the parent
        // container, so they have no ordering dependencies on each other and can
        // be stopped in parallel (the parent is released afterwards, separately).
        // Stop every component even if one throws, so a single failed stop can't
        // leak the resources owned by another. Every stop error is collected and
        // rethrown together once teardown is done.
        const results = await Promise.allSettled(
            started.map(async (s) => {
                logger.info(`Scope[${this.name}]: stopping ${s.name}`)
                try {
                    await s.stop()
                } catch (err) {
                    logger.error(`Scope[${this.name}]: ${s.name} stop failed`, { error: err })
                    throw err
                }
            })
        )

        const errors = results.flatMap((result) => (result.status === 'rejected' ? [result.reason] : []))
        if (errors.length > 0) {
            throw new AggregateError(errors, `Scope[${this.name}]: ${errors.length} component(s) failed to stop`)
        }
    }
}
