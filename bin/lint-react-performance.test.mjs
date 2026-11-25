import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const script = join(dirname(fileURLToPath(import.meta.url)), 'lint-react-performance.mjs')

for (const [name, source, expected] of [
    [
        'nested lookup',
        'export const Canvas = ({ blocks, cells }) => blocks.map(block => <Cell cell={cells.find(cell => cell.id === block.node_id)} />)',
        1,
    ],
    ['single lookup', 'export const Canvas = ({ cells, id }) => <Cell cell={cells.find(cell => cell.id === id)} />', 0],
    [
        'indexed lookup',
        'export const Canvas = ({ blocks, cellsById }) => blocks.map(block => <Cell cell={cellsById.get(block.node_id)} />)',
        0,
    ],
    [
        'different collections',
        'export const Canvas = ({ groups }) => groups.map(group => <Cell cell={group.cells.find(cell => cell.id === group.id)} />)',
        0,
    ],
    [
        'event handler',
        'export const Canvas = ({ blocks, cells }) => blocks.map(block => <Cell onClick={() => cells.find(cell => cell.id === block.node_id)} />)',
        0,
    ],
    [
        'destructured collections',
        'export const Canvas = ({ groups }) => groups.map(({ cells, id }) => <Cell cell={cells.find(cell => cell.id === id)} />)',
        0,
    ],
    [
        'local collection',
        'export const Canvas = ({ groups }) => groups.map(group => { const cells = group.cells; return <Cell cell={cells.find(cell => cell.id === group.id)} /> })',
        0,
    ],
]) {
    test(name, () => {
        const root = mkdtempSync(join(tmpdir(), 'react-performance-'))
        try {
            execFileSync('git', ['init', '--quiet', root])
            mkdirSync(join(root, 'frontend/src'), { recursive: true })
            writeFileSync(join(root, 'frontend/src/changed.tsx'), source)
            writeFileSync(
                join(root, 'frontend/src/untouched.tsx'),
                'export const Other = ({ rows, cells }) => rows.map(row => cells.find(cell => cell.id === row.id))'
            )
            const result = spawnSync(process.execPath, [script, 'frontend/src/changed.tsx'], {
                cwd: root,
                encoding: 'utf8',
            })
            assert.equal(result.status, expected, result.stdout + result.stderr)
            assert.doesNotMatch(result.stdout + result.stderr, /untouched\.tsx/)
            if (expected === 1) {
                assert.match(result.stdout + result.stderr, /react-performance\(no-repeated-array-lookup\)/)
            }
        } finally {
            rmSync(root, { recursive: true, force: true })
        }
    })
}
