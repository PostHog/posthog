import { PassThrough } from 'stream'

import { SessionBatchWriter, StreamWithFinish } from './session-batch-recorder'

export class BlackholeSessionBatchWriter implements SessionBatchWriter {
    public async open(): Promise<StreamWithFinish> {
        return Promise.resolve({
            stream: new PassThrough(),
            finish: async () => Promise.resolve(),
        })
    }
}
