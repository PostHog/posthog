/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Builds the replay-anonymizer Rust addon and copies it to native/, where src/pixel-convert.ts loads
 * it from. The image builds the same crate in a Rust stage of Dockerfile.ml-mirror-image-scrub.
 *
 * Needs a Rust toolchain. Run it again after any change under rust/replay-anonymizer-node or
 * rust/replay-anonymizer, because the sidecar loads whatever binary native/ holds.
 */
import { execFileSync } from 'node:child_process'
import { copyFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const RUST_WORKSPACE = fileURLToPath(new URL('../../../../../../../rust/', import.meta.url))
const NATIVE_DIR = fileURLToPath(new URL('../native/', import.meta.url))

interface CargoMessage {
    reason: string
    target?: { name: string }
    filenames?: string[]
}

const stdout = execFileSync(
    'cargo',
    ['build', '--release', '--locked', '-p', 'replay-anonymizer-node', '--message-format=json-render-diagnostics'],
    { cwd: RUST_WORKSPACE, stdio: ['ignore', 'pipe', 'inherit'], maxBuffer: 1 << 30 }
)
const library = stdout
    .toString()
    .split('\n')
    .filter((line) => line.startsWith('{'))
    .map((line) => JSON.parse(line) as CargoMessage)
    .filter((message) => message.reason === 'compiler-artifact' && message.target?.name === 'replay_anonymizer_node')
    .flatMap((message) => message.filenames ?? [])
    .find((file) => /\.(so|dylib)$/.test(file))
if (!library) {
    throw new Error('cargo reported no replay_anonymizer_node library')
}
mkdirSync(NATIVE_DIR, { recursive: true })
copyFileSync(library, `${NATIVE_DIR}replay-anonymizer.node`)
console.log(`copied ${library} to native/replay-anonymizer.node`)
