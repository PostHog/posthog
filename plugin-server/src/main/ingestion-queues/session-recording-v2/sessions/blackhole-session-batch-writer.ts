import { PassThrough } from 'stream'

import { status } from '../../../../utils/status'
import { SessionBatchFileWriter, StreamWithFinish } from './session-batch-file-writer'

export class BlackholeSessionBatchWriter implements SessionBatchFileWriter {
    public newBatch(): StreamWithFinish {
        status.debug('🔁', 'blackhole_writer_creating_stream')
        const stream = new PassThrough()

        stream.on('data', () => {})

        return {
            stream,
            finish: async () => {
                status.debug('🔁', 'blackhole_writer_finishing_stream')
                return Promise.resolve()
            },
        }
    }
}
