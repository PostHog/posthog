import { Startable, StartedScope } from './scope'

/**
 * The bottom of every scope tree: a parent that contributes nothing. Its
 * container is empty and its lifecycle is a no-op, so a root scope is just
 * a `ScopeRunner` extending over this. Deliberately silent — it emits no
 * logs and holds no refcount, since it has a single consumer and nothing
 * to tear down.
 */
export class EmptyScope implements Startable<Record<never, object>> {
    start(): Promise<StartedScope<Record<never, object>>> {
        return Promise.resolve({
            name: '∅',
            container: {},
            stop: () => Promise.resolve(),
        })
    }
}
