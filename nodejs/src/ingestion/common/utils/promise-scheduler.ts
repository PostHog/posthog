import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { Component } from '~/ingestion/common/scopes'

export { PromiseScheduler } from '~/common/utils/promise-scheduler'

/**
 * Wraps an internally-owned `PromiseScheduler` as a scope entry. Start is
 * a no-op (the scheduler is alive from construction); stop drains all
 * pending background work via `waitForAll()` so any side effects
 * scheduled during processing get awaited before the scope tears down.
 */
export class PromiseSchedulerComponent implements Component<PromiseScheduler> {
    private readonly scheduler = new PromiseScheduler()

    start(): Promise<{ value: PromiseScheduler; stop: () => Promise<void> }> {
        return Promise.resolve({
            value: this.scheduler,
            stop: () => this.scheduler.waitForAll().then(() => undefined),
        })
    }
}
