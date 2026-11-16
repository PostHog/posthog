// Records container goldens from the Rust oracle. Run from hog/ after building the oracle:
//   (cd ../cli && cargo build --release --example hog_parity_oracle)
//   bun test/parity/record-containers.ts <path to hog_parity_oracle>
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { CONTAINER_CASES } from './containers'
import { generateInput } from './inputs'

const oracle = process.argv[2]
if (!oracle) {
    throw new Error('Pass the path to the hog_parity_oracle binary.')
}
const folder = mkdtempSync(join(tmpdir(), 'hog-parity-'))
const golden = CONTAINER_CASES.map((testCase) => {
    const file = join(folder, 'input')
    writeFileSync(file, generateInput(testCase.input))
    const result = Bun.spawnSync([oracle, 'container', testCase.type, file])
    if (result.exitCode !== 0) {
        throw new Error(`oracle failed for ${JSON.stringify(testCase)}: ${result.stderr.toString()}`)
    }
    return { ...testCase, hash: result.stdout.toString().trim() }
})
writeFileSync(join(import.meta.dir, 'golden', 'containers.json'), `${JSON.stringify(golden, null, 2)}\n`)
process.stdout.write(`Recorded ${golden.length} container goldens.\n`)
