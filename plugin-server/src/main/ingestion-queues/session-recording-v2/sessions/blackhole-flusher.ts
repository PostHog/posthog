import { PassThrough } from 'stream'

import { SessionBatchFlusher, StreamWithFinish } from './session-batch-recorder'

export class BlackholeFlusher implements SessionBatchFlusher {
    public async open(): Promise<StreamWithFinish> {
        return Promise.resolve({
            stream: new PassThrough(),
            finish: async () => Promise.resolve(),
        })
    }
}
