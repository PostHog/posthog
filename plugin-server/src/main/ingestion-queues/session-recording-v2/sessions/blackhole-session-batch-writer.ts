import { Writable } from 'stream'

import { SessionBatchWriter, StreamWithFinish } from './session-batch-recorder'

class BlackholeStream extends Writable {
    constructor() {
        super()
    }

    _write(chunk: any, encoding: string, callback: (error?: Error | null) => void): void {
        // Immediately discard the data and signal we're ready for more
        callback()
    }
}

export class BlackholeSessionBatchWriter implements SessionBatchWriter {
    public async open(): Promise<StreamWithFinish> {
        return Promise.resolve({
            stream: new BlackholeStream(),
            finish: async () => {
                return Promise.resolve()
            },
        })
    }
}
