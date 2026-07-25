/**
 * One inference worker: owns its own ONNX sessions and scrubs one image at a time.
 *
 * The whole scrub runs here rather than just the model calls, because onnxruntime-node's `run`
 * blocks the thread it is called on, so leaving anything else on that thread only serialises it
 * behind the inference. Sessions cannot be shared across isolates, so each worker loads its own.
 */
import { parentPort } from 'node:worker_threads'

import { UndecodableImageError } from './blur.ts'
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
            // Deliberately copied rather than transferred. The output can be the shared BLANK_PNG
            // constant, which lives in Node's small-buffer pool, and an 8 KiB pool ArrayBuffer is not
            // transferable: attempting it throws DataCloneError on exactly the NSFW-gated path this
            // service exists to handle. A PNG-sized copy costs microseconds against a scrub.
            port.postMessage({ id: job.id, out, timings: t } satisfies ScrubReply)
        })
        .catch((error: unknown) => {
            // Structured clone drops the prototype, so the one distinction the HTTP layer acts on
            // (422 permanent versus 500 retriable) has to travel as data rather than as a class.
            port.postMessage({
                id: job.id,
                failure: {
                    message: error instanceof Error ? error.message : String(error),
                    undecodable: error instanceof UndecodableImageError,
                },
            } satisfies ScrubReply)
        })
})
