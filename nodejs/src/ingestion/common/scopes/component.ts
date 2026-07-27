/** A started value paired with the `stop` callback that tears it down. */
export interface Started<T> {
    value: T
    stop: () => Promise<void>
}

/**
 * Defines the lifecycle of a single container value. `start()` produces the
 * value plus a `stop` callback that tears it down. Anyone holding the value
 * only sees the business interface — the start/stop pair stays with the
 * component. This lets the scope plumb dependencies (services, pools, config)
 * through a single container without each entry needing to wear a
 * start/stop hat.
 */
export interface Component<T> {
    start(): Promise<Started<T>>
}

export type ValueOf<C> = C extends Component<infer T> ? T : never

/** Maps each container key to the `Component` that produces its value. */
export type ComponentMap<S> = { [K in keyof S]: Component<S[K]> }
