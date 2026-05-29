import { logger } from '../../../utils/logger'
import { Component, Started } from './component'
import { Scope } from './scope'
import { ScopeBuilder } from './scope-builder'

/**
 * Runs a child scope on top of a parent scope. `start` starts (or refcounts
 * onto) the parent, resolves its container, hands it to the configure
 * callback to build a child scope, then starts the child. The returned
 * `stop` stops the child then releases the parent. The parent boot is
 * shared across all extensions rooted at it via the parent's own refcount.
 */
export class ExtendedRunner<SParent extends Record<string, object>, SChild extends Record<string, object>>
    implements Component<SParent & SChild>
{
    constructor(
        private readonly parent: Scope<SParent>,
        private readonly configure: (
            parentContainer: SParent,
            builder: ScopeBuilder<Record<never, object>>
        ) => ScopeBuilder<SChild>,
        private readonly childName: string
    ) {}

    async start(): Promise<Started<SParent & SChild>> {
        logger.info(`Scope[${this.childName}]: acquiring parent ${this.parent.name}`)
        const parentHandle = await this.parent.start()
        try {
            const childScope = this.configure(parentHandle.container, ScopeBuilder.empty()).build(this.childName)
            const childHandle = await childScope.start()
            return {
                value: { ...parentHandle.container, ...childHandle.container },
                stop: async (): Promise<void> => {
                    try {
                        await childHandle.stop()
                    } finally {
                        logger.info(`Scope[${this.childName}]: releasing parent ${this.parent.name}`)
                        await parentHandle.stop()
                    }
                },
            }
        } catch (err) {
            logger.error(`Scope[${this.childName}]: extend start failed, releasing parent ${this.parent.name}`, {
                error: err,
            })
            try {
                await parentHandle.stop()
            } catch (parentStopErr) {
                logger.error(`Scope[${this.childName}]: parent ${this.parent.name} stop failed during rollback`, {
                    error: parentStopErr,
                })
            }
            throw err
        }
    }
}
