// Records end-to-end goldens by running posthog-cli against the fake server. Run from hog/:
//   (cd ../cli && cargo build --release)
//   bun test/parity/record-e2e.ts <path to posthog-cli> [scenario name...]
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { runScenario } from './run'
import { SCENARIOS } from './scenarios'

const [binary, ...only] = process.argv.slice(2)
if (!binary) {
    throw new Error('Pass the path to a posthog-cli binary built with `cargo build --release`.')
}
const folder = join(import.meta.dir, 'golden', 'e2e')
mkdirSync(folder, { recursive: true })
for (const scenario of SCENARIOS.filter((candidate) => only.length === 0 || only.includes(candidate.name))) {
    const result = await runScenario(scenario, { rust: binary })
    writeFileSync(join(folder, `${scenario.name}.json`), `${JSON.stringify(result, null, 2)}\n`)
    process.stdout.write(`${scenario.name}: exit ${result.exitCode}, ${result.requests.length} requests\n`)
}
