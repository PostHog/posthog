import { Component, ComponentMap, ValueOf } from './component'
import { ComponentRunner } from './runner'
import { Scope } from './scope'

/**
 * Per-scope accumulator. `add` records a `Component` for each entry;
 * the corresponding value lands in the container only after the scope
 * starts. Until then, the builder is just a typed recipe.
 */
export class ScopeBuilder<S extends Record<string, object> = Record<never, object>> {
    private constructor(private readonly components: ComponentMap<S>) {}

    static empty(): ScopeBuilder<Record<never, object>> {
        return new ScopeBuilder<Record<never, object>>({})
    }

    add<Name extends string, C extends Component<object>>(
        name: Name & (Name extends keyof S ? never : Name),
        component: C
    ): ScopeBuilder<S & Record<Name, ValueOf<C>>> {
        // Adding the `name` key with its `component` produces exactly
        // `ComponentMap<S & Record<Name, ValueOf<C>>>`, but a computed-key
        // spread only types as a string index signature, so assert the shape
        // the method signature already guarantees.
        const components: Record<string, Component<object>> = { ...this.components, [name]: component }
        return new ScopeBuilder<S & Record<Name, ValueOf<C>>>(components as ComponentMap<S & Record<Name, ValueOf<C>>>)
    }

    build(name: string): Scope<S> {
        const runner = new ComponentRunner<S>(name, this.components)
        return new Scope<S>(name, () => runner.getContainer(), runner)
    }
}
