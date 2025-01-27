import { PassThrough } from 'stream'

import { SessionBatchWriter, StreamWithFinish } from './session-batch-recorder'

export class BlackholeSessionBatchWriter implements SessionBatchWriter {
    public async open(): Promise<StreamWithFinish> {
        const stream = new PassThrough()

        stream.on('data', () => {})

        return Promise.resolve({
            stream,
            finish: async () => Promise.resolve(),
        })
    }
}
