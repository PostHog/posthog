// A process rather than a worker thread, because only a process can be stopped inside a native call.
import { createRequire } from 'node:module'
import { resolve } from 'node:path'

const ADDON_PATH = resolve('native/replay-anonymizer.node')
const { rasterizeSvg } = createRequire(ADDON_PATH)(ADDON_PATH)
if (typeof rasterizeSvg !== 'function') {
    throw new Error(`the native addon at ${ADDON_PATH} has no rasterizeSvg; rebuild it with \`npm run build:native\``)
}

process.on('message', ({ id, input }) => {
    let reply
    try {
        reply = { id, out: rasterizeSvg(input) }
    } catch (error) {
        reply = { id, refused: error instanceof Error ? error.message : String(error) }
    }
    process.send(reply)
})
process.send({ ready: true })
