import { execFileSync } from 'node:child_process'
import { appendFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const FRONTEND = fileURLToPath(new URL('../../frontend/', import.meta.url))
const RUNTIME_CONFIG = 'jest.probe.config.ts'

const SCENARIOS = [
    ['hub_types', 'src/types.ts'],
    ['cycle_logic', 'src/scenes/dashboard/dashboardLogic.tsx'],
    ['leaf_component', 'src/lib/components/Errors/Frame/CollapsibleFrameContent.tsx'],
    ['generated_schema', '../products/data_warehouse/frontend/generated/api.schemas.ts'],
    ['leaf_util', 'src/lib/utils/botDetection.ts'],
]

function listTests(config, file) {
    const args = ['exec', 'jest', '--listTests']
    if (config) {
        args.push('--config', config)
    }
    if (file) {
        args.push('--findRelatedTests', file)
    }
    const started = Date.now()
    const out = execFileSync('pnpm', args, { cwd: FRONTEND, encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 })
    const tests = out.split('\n').filter((line) => line.startsWith('/')).length
    return { tests, seconds: Math.round((Date.now() - started) / 100) / 10 }
}

const counts = {}
counts.all = { default: listTests('', ''), runtime: listTests(RUNTIME_CONFIG, '') }
for (const [name, file] of SCENARIOS) {
    counts[name] = { file, default: listTests('', file), runtime: listTests(RUNTIME_CONFIG, file) }
}
console.log(`PROBE_COUNTS ${JSON.stringify(counts)}`)

const include = []
function arm(name, file, config, tests, shards, workers, rep) {
    for (let chunk = 1; chunk <= shards; chunk++) {
        include.push({ arm: name, file, config, tests, shards, chunk, workers, rep })
    }
}
const hub = counts.hub_types
const cycle = counts.cycle_logic
const util = counts.leaf_util
for (const rep of [1, 2]) {
    for (const workers of ['default', '100%']) {
        for (const shards of [3, 4, 6]) {
            arm('default_hub', hub.file, '', hub.default.tests, shards, workers, rep)
        }
    }
    arm('runtime_cycle', cycle.file, RUNTIME_CONFIG, cycle.runtime.tests, 2, 'default', rep)
}
arm('default_util', util.file, '', util.default.tests, 1, 'default', 1)

console.log(`PROBE_MATRIX_CELLS ${include.length}`)
appendFileSync(process.env.GITHUB_OUTPUT, `matrix=${JSON.stringify({ include })}\n`)
