import { logger } from '../../../utils/logger'
import { CallerSet } from './caller-set'
import { ExtendedRunner } from './extended-runner'
import { Runner } from './runner'
import { ScopeBuilder } from './scope-builder'
import { ScopeContext, StateMachine } from './state-machine'

/**
 * Returned by `Scope.start()`. The handle's `stop` removes this caller
 * from the refcount and is single-shot — calling it twice has no effect
 * after the first call.
 */
export interface StartedScope<S extends Record<string, object>> {
    readonly name: string
    readonly container: S
    readonly stop: () => Promise<void>
}

/**
 * The owning system: assembles a state machine, refcount, and runner into
 * a startable, refcounted handle over a container of started values.
 */
export class Scope<S extends Record<string, object> = Record<never, object>> {
    private readonly machine = new StateMachine()
    private readonly callers = new CallerSet()
    private readonly containerProvider: () => S
    private readonly runner: Runner
    private readonly ctx: ScopeContext

    constructor(
        readonly name: string,
        containerProvider: () => S,
        runner: Runner
    ) {
        this.containerProvider = containerProvider
        this.runner = runner
        this.ctx = {
            runStart: () => this.runner.start(),
            runStop: () => this.runner.stop(),
            callerCount: () => this.callers.size(),
        }
    }

    async start(): Promise<StartedScope<S>> {
        const release = this.callers.register()
        logger.info(`Scope[${this.name}]: start requested (callers=${this.callers.size()})`)
        try {
            await this.machine.start(this.ctx)
        } catch (err) {
            release()
            logger.error(`Scope[${this.name}]: start failed`, { error: err })
            throw err
        }
        logger.info(`Scope[${this.name}]: started`)
        return this.makeHandle(release)
    }

    /**
     * Build a child scope on top of this one. The `configure` callback
     * receives this scope's started container and a fresh builder, and
     * returns the builder with the child's entries registered. The returned
     * scope's container is `parent ∪ child`.
     *
     * On `start`: this scope is started (or refcounted onto), then the
     * callback runs with the resolved container and the child is started.
     * On `stop`: the child is stopped, then this scope is released.
     */
    extend<S2 extends Record<string, object>>(
        name: string,
        configure: (parentContainer: S, builder: ScopeBuilder<Record<never, object>>) => ScopeBuilder<S2>
    ): Scope<S & S2> {
        const runner = new ExtendedRunner<S, S2>(this, configure, name)
        return new Scope<S & S2>(name, () => runner.getContainer(), runner)
    }

    private makeHandle(release: () => boolean): StartedScope<S> {
        return {
            name: this.name,
            container: this.containerProvider(),
            stop: async (): Promise<void> => {
                if (!release()) {
                    return
                }
                logger.info(`Scope[${this.name}]: stop requested (callers=${this.callers.size()})`)
                try {
                    await this.machine.stop(this.ctx)
                } catch (err) {
                    logger.error(`Scope[${this.name}]: stop failed`, { error: err })
                    throw err
                }
                logger.info(`Scope[${this.name}]: stopped`)
            },
        }
    }
}

/**
 * Builds a root scope with the given name. The `configure` callback
 * receives an empty builder and returns the builder with the scope's
 * entries registered. Mirrors `Scope.extend` so root and child scopes
 * have the same construction shape.
 */
export function newScope<S extends Record<string, object>>(
    name: string,
    configure: (builder: ScopeBuilder<Record<never, object>>) => ScopeBuilder<S>
): Scope<S> {
    return configure(ScopeBuilder.empty()).build(name)
}
