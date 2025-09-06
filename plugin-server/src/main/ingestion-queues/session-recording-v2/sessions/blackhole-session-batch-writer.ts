import { logger } from '../../../../utils/logger'
import {
    SessionBatchFileStorage,
    SessionBatchFileWriter,
    WriteSessionData,
    WriteSessionResult,
} from './session-batch-file-storage'

class BlackholeBatchFileWriter implements SessionBatchFileWriter {
    public writeSession(sessionData: WriteSessionData): Promise<WriteSessionResult> {
        logger.debug('🔁', 'blackhole_writer_writing_session', { bytes: sessionData.buffer.length })
        return Promise.resolve({
            bytesWritten: sessionData.buffer.length,
            url: null,
            retentionPeriodDays: null,
        })
    }

    public finish(): Promise<void> {
        logger.debug('🔁', 'blackhole_writer_finishing_batch')
        return Promise.resolve()
    }
}

export class BlackholeSessionBatchFileStorage implements SessionBatchFileStorage {
    public newBatch(): SessionBatchFileWriter {
        logger.debug('🔁', 'blackhole_writer_creating_batch')
        return new BlackholeBatchFileWriter()
    }

    public checkHealth(): Promise<boolean> {
        logger.debug('🔁', 'blackhole_writer_healthcheck')
        return Promise.resolve(true)
    }
}
