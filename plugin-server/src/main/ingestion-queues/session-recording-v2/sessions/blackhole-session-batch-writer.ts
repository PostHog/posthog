import { status } from '../../../../utils/status'
import { SessionBatchFileStorage, SessionBatchFileWriter, WriteSessionResult } from './session-batch-file-storage'

class BlackholeBatchFileWriter implements SessionBatchFileWriter {
    public writeSession(buffer: Buffer): Promise<WriteSessionResult> {
        status.debug('🔁', 'blackhole_writer_writing_session', { bytes: buffer.length })
        return Promise.resolve({
            bytesWritten: buffer.length,
            url: null,
        })
    }

    public finish(): Promise<void> {
        status.debug('🔁', 'blackhole_writer_finishing_batch')
        return Promise.resolve()
    }
}

export class BlackholeSessionBatchFileStorage implements SessionBatchFileStorage {
    public newBatch(): SessionBatchFileWriter {
        status.debug('🔁', 'blackhole_writer_creating_batch')
        return new BlackholeBatchFileWriter()
    }

    public checkHealth(): Promise<boolean> {
        status.debug('🔁', 'blackhole_writer_healthcheck')
        return Promise.resolve(true)
    }
}
