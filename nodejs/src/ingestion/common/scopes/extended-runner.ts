import { logger } from '../../../utils/logger'
import { Runner } from './runner'
import { Scope, StartedScope } from './scope'
import { ScopeBuilder } from './scope-builder'

/**
 * Runs a child scope on top of a parent scope. On `start`: start
 * (or refcount onto) the parent, resolve its container, hand it to the
 * configure callback to build a child scope, then start the child.
 * On `stop`: stop the child then release the parent. The parent boot is
 * shared across all extensions rooted at it via the parent's own refcount.
 */
export class ExtendedRunner<SParent extends Record<string, object>, SChild extends Record<string, object>>
    implements Runner
{
    private parentHandle?: StartedScope<SParent>
    private childHandle?: StartedScope<SChild>
    private containerCache?: SParent & SChild

    constructor(
        private readonly parent: Scope<SParent>,
        private readonly configure: (
            parentContainer: SParent,
            builder: ScopeBuilder<Record<never, object>>
        ) => ScopeBuilder<SChild>,
        private readonly childName: string
    ) {}

    async start(): Promise<void> {
        logger.info(`Scope[${this.childName}]: acquiring parent ${this.parent.name}`)
        const parentHandle = await this.parent.start()
        try {
            const childScope = this.configure(parentHandle.container, ScopeBuilder.empty()).build(this.childName)
            const childHandle = await childScope.start()
            this.parentHandle = parentHandle
            this.childHandle = childHandle
            this.containerCache = { ...parentHandle.container, ...childHandle.container }
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

    async stop(): Promise<void> {
        const childHandle = this.childHandle
        const parentHandle = this.parentHandle
        this.childHandle = undefined
        this.parentHandle = undefined
        this.containerCache = undefined
        try {
            if (childHandle) {
                await childHandle.stop()
            }
        } finally {
            if (parentHandle) {
                logger.info(`Scope[${this.childName}]: releasing parent ${this.parent.name}`)
                await parentHandle.stop()
            }
        }
    }

    getContainer(): SParent & SChild {
        if (!this.containerCache) {
            throw new Error(`extended scope "${this.childName}" is not started`)
        }
        return this.containerCache
    }
}
