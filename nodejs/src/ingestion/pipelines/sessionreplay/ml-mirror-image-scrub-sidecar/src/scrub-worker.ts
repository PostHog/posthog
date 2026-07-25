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
    advancedScrub(input, models).then(
        ({ out, t }) => port.postMessage({ id: job.id, out, timings: t } satisfies ScrubReply, [out.buffer]),
        (error: unknown) =>
            port.postMessage({
                id: job.id,
                // Structured clone drops the prototype, so the one distinction the HTTP layer acts on
                // (422 permanent versus 500 retriable) has to travel as data rather than as a class.
                failure: {
                    message: error instanceof Error ? error.message : String(error),
                    undecodable: error instanceof UndecodableImageError,
                },
            } satisfies ScrubReply)
    )
})
