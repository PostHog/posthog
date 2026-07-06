import { Component } from '~/ingestion/common/scopes'

import { PostgresRouter } from './db/postgres'
import { EventSchemaEnforcementManager } from './event-schema-enforcement-manager'

/**
 * Scope owner for the `EventSchemaEnforcementManager`. The manager holds only an
 * in-memory `LazyLoader` cache over the shared Postgres router (which it does not
 * own), so `start()` just constructs it and `stop()` is a no-op — the cache is
 * released with the manager when the scope tears down. Owning it as a component
 * keeps lifecycle uniform with the rest of the container and gives a place to wire
 * teardown if the manager ever acquires a resource that needs it.
 */
export class EventSchemaEnforcementManagerComponent implements Component<EventSchemaEnforcementManager> {
    constructor(private readonly postgres: PostgresRouter) {}

    start(): Promise<{ value: EventSchemaEnforcementManager; stop: () => Promise<void> }> {
        return Promise.resolve({
            value: new EventSchemaEnforcementManager(this.postgres),
            stop: () => Promise.resolve(),
        })
    }
}
