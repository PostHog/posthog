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
        'performance diagnostic',
        'export const Example = ({ rows }) => <div>{JSON.parse(JSON.stringify(rows)).length}</div>',
        1,
    ],
    ['clean component', 'export const Example = () => <button type="button">Hello</button>', 0],
]) {
    test(name, () => {
        const root = mkdtempSync(join(tmpdir(), 'react-performance-'))
        try {
            execFileSync('git', ['init', '--quiet', root])
            writeFileSync(
                join(root, 'package.json'),
                JSON.stringify({ name: 'performance-test', private: true, dependencies: { react: '18.3.1' } })
            )
            mkdirSync(join(root, 'frontend/src'), { recursive: true })
            writeFileSync(join(root, 'frontend/src/changed.tsx'), source)
            writeFileSync(
                join(root, 'frontend/src/untouched.tsx'),
                'export const Other = ({ rows }) => <div>{JSON.parse(JSON.stringify(rows)).length}</div>'
            )
            const result = spawnSync(process.execPath, [script, 'frontend/src/changed.tsx'], {
                cwd: root,
                encoding: 'utf8',
            })
            assert.equal(result.status, expected, result.stdout + result.stderr)
            assert.doesNotMatch(result.stdout + result.stderr, /untouched\.tsx/)
            if (expected === 1) {
                assert.match(result.stdout + result.stderr, /JSON\.parse|json-parse/)
            }
        } finally {
            rmSync(root, { recursive: true, force: true })
        }
    })
}
