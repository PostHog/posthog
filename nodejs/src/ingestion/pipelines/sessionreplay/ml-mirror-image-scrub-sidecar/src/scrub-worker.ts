/**
 * One inference worker: owns its own ONNX sessions and scrubs one image at a time.
 *
 * The whole scrub runs here rather than just the model calls, because onnxruntime-node's `run`
 * blocks the thread it is called on, so leaving anything else on that thread only serialises it
 * behind the inference. Sessions cannot be shared across isolates, so each worker loads its own.
 */
import { parentPort } from 'node:worker_threads'

import { UndecodableImageError } from './blur.ts'
import { ImageOptOutError } from './image-input.ts'
import { advancedScrub, loadModels } from './scrub.ts'
import { type ScrubJob, type ScrubReply } from './worker-protocol.ts'

if (!parentPort) {
    throw new Error('scrub-worker must be started as a worker thread')
}
const port = parentPort

// Loaded before the ready signal, so the pool only reports itself up once every worker can scrub.
const models = await loadModels()
port.postMessage({ ready: true } satisfies ScrubReply)

port.on('message', (job: ScrubJob) => {
    const input = Buffer.from(job.input.buffer, job.input.byteOffset, job.input.byteLength)
    // Catch rather than pass a rejection handler, so a throw while replying is reported as a failed
    // job instead of becoming an unhandled rejection that takes the whole worker down with it.
    advancedScrub(input, models)
        .then(({ out, t }) => {
            // Copied, never transferred: nothing this returns has a transferable backing store, so a
            // transfer list throws DataCloneError on every reply rather than on some edge case.
            // sharp hands back a napi external ArrayBuffer, which is not detachable even when it is
            // exactly sized, and the safety gate's BLANK_PNG is carved from Node's shared 8 KiB
            // buffer pool. A PNG-sized copy costs microseconds against a scrub, so there is nothing
            // to reclaim by trying to be clever here.
            port.postMessage({ id: job.id, out, timings: t } satisfies ScrubReply)
        })
        .catch((error: unknown) => {
            // Structured clone drops the prototype, so the one distinction the HTTP layer acts on
            // (422 permanent versus 500 retriable) has to travel as data rather than as a class.
            port.postMessage({
                id: job.id,
                failure: {
                    message: error instanceof Error ? error.message : String(error),
                    kind:
                        error instanceof ImageOptOutError
                            ? 'opt-out'
                            : error instanceof UndecodableImageError
                              ? 'undecodable'
                              : 'failed',
                },
            } satisfies ScrubReply)
        })
})
