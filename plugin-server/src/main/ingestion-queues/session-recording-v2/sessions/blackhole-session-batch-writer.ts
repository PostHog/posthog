import { PassThrough } from 'stream'

import { status } from '../../../../utils/status'
import { SessionBatchWriter, StreamWithFinish } from './session-batch-recorder'

export class BlackholeSessionBatchWriter implements SessionBatchWriter {
    public async open(): Promise<StreamWithFinish> {
        status.debug('🔁', 'blackhole_writer_creating_stream')
        const stream = new PassThrough()

        stream.on('data', () => {})

        return Promise.resolve({
            stream,
            finish: async () => {
                status.debug('🔁', 'blackhole_writer_finishing_stream')
                return Promise.resolve()
            },
        })
    }
}
