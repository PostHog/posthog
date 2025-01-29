import { Writable } from 'stream'

export interface StreamWithFinish {
    stream: Writable
    finish: () => Promise<void>
}

export interface SessionBatchWriter {
    open(): Promise<StreamWithFinish>
}
