import { Component } from '~/common/scopes/component'
import { logger } from '~/common/utils/logger'

import { CallerSet } from './caller-set'
import { ScopeRunner } from './runner'
import { ScopeBuilder } from './scope-builder'

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
 * Anything a `ScopeRunner` can sit on top of: it starts into a container
 * and a stop. Both `Scope` (refcounted, logged) and `EmptyScope` (the
 * silent bottom of every tree) satisfy it.
 */
export interface Startable<S extends Record<string, object>> {
    start(): Promise<StartedScope<S>>
}

/**
 * The owning system: wraps a `Component` in a refcount so concurrent and
 * repeated callers share a single boot, and the underlying component is
 * torn down only once the last caller releases. Start and stop never run
 * concurrently: an in-flight transition is awaited before the next one is
 * evaluated, and the started state is re-checked afterwards.
 */
export class Scope<S extends Record<string, object> = Record<never, object>> implements Startable<S> {
    private readonly callers = new CallerSet()
    private transition: Promise<void> | null = null
    private current?: { value: S; stop: () => Promise<void> }

    constructor(
        readonly name: string,
        private readonly component: Component<S>
    ) {}

    async start(): Promise<StartedScope<S>> {
        const release = this.callers.register()
        logger.info(`Scope[${this.name}]: start requested (callers=${this.callers.size()})`)
        try {
            await this.ensureStarted()
        } catch (err) {
            release()
            logger.error(`Scope[${this.name}]: start failed`, { error: err })
            throw err
        }
        logger.info(`Scope[${this.name}]: started`)
        const container = this.current!.value
        return {
            name: this.name,
            container,
            stop: () => this.releaseCaller(release),
        }
    }

    private async ensureStarted(): Promise<void> {
        while (this.transition) {
            await this.transition
        }
        if (this.current) {
            return
        }
        const boot = this.component.start().then((result) => {
            this.current = result
        })
        this.transition = boot.finally(() => {
            this.transition = null
        })
        await this.transition
    }

    private async releaseCaller(release: () => boolean): Promise<void> {
        if (!release()) {
            return
        }
        logger.info(`Scope[${this.name}]: stop requested (callers=${this.callers.size()})`)
        try {
            await this.ensureStoppedWhenIdle()
        } catch (err) {
            logger.error(`Scope[${this.name}]: stop failed`, { error: err })
            throw err
        }
        logger.info(`Scope[${this.name}]: stopped`)
    }

    private async ensureStoppedWhenIdle(): Promise<void> {
        while (this.transition) {
            await this.transition
        }
        if (this.callers.size() > 0 || !this.current) {
            return
        }
        const result = this.current
        const teardown = result.stop().finally(() => {
            this.current = undefined
        })
        this.transition = teardown.finally(() => {
            this.transition = null
        })
        await this.transition
    }
}

/**
 * Builds a root scope with the given name. The `configure` callback
 * receives an empty builder and returns the builder with the scope's
 * entries registered. A root is just an extension over the empty bottom,
 * so its container has no parent entries.
 */
export function newScope<S extends Record<string, object>>(
    name: string,
    configure: (builder: ScopeBuilder<Record<never, object>>) => ScopeBuilder<S>
): Scope<S> {
    return configure(ScopeBuilder.empty()).build(name)
}

/**
 * Builds a child scope on top of `parent`. The `configure` callback
 * receives the parent's started container and a fresh builder, and returns
 * the builder with the child's entries registered. The child's container
 * is `parent ∪ child`; a child entry that reuses a parent key overrides it
 * in the merged container, while both still run their own lifecycles.
 *
 * On `start`: the parent is started (or refcounted onto), then the callback
 * runs with the resolved container and the child entries are started.
 * On `stop`: the child entries are stopped, then the parent is released.
 */
export function extend<S extends Record<string, object>, S2 extends Record<string, object>>(
    parent: Scope<S>,
    name: string,
    configure: (parentContainer: S, builder: ScopeBuilder<Record<never, object>>) => ScopeBuilder<S2>
): Scope<S & S2> {
    return new Scope<S & S2>(
        name,
        new ScopeRunner<S, S2>(
            parent,
            (parentContainer) => configure(parentContainer, ScopeBuilder.empty()).components(),
            name
        )
    )
}
