import { logger } from '../../../../utils/logger'
import { RetentionPeriod } from '../types'
import { SessionBatchFileStorage, SessionBatchFileWriter, WriteSessionResult } from './session-batch-file-storage'

class BlackholeBatchFileWriter implements SessionBatchFileWriter {
    public writeSession(buffer: Buffer): Promise<WriteSessionResult> {
        logger.debug('🔁', 'blackhole_writer_writing_session', { bytes: buffer.length })
        return Promise.resolve({
            bytesWritten: buffer.length,
            url: null,
        })
    }

    public finish(): Promise<void> {
        logger.debug('🔁', 'blackhole_writer_finishing_batch')
        return Promise.resolve()
    }
}

export class BlackholeSessionBatchFileStorage implements SessionBatchFileStorage {
    public startBatch(): void {
        logger.debug('🔁', 'blackhole_writer_creating_batch')
    }

    public getWriter(_: RetentionPeriod): SessionBatchFileWriter {
        logger.debug('🔁', 'blackhole_writer_get')
        return new BlackholeBatchFileWriter()
    }

    public endBatch(): Promise<void> {
        logger.debug('🔁', 'blackhole_writer_ending_batch')
        return Promise.resolve()
    }

    public checkHealth(): Promise<boolean> {
        logger.debug('🔁', 'blackhole_writer_healthcheck')
        return Promise.resolve(true)
    }
}
