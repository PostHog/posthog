import { PassThrough, Writable } from 'stream'

import { SessionBatchFlusher } from './session-batch-recorder'

export class BlackholeFlusher implements SessionBatchFlusher {
    public async open(): Promise<Writable> {
        return Promise.resolve(new PassThrough())
    }

    public async finish(): Promise<void> {
        return Promise.resolve()
    }
}
