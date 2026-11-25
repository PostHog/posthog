import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, isAbsolute, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

const toolRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: { base: { type: 'string', default: 'origin/master' } },
})

function git(...args) {
    return execFileSync('git', args, { encoding: 'utf8' }).trimEnd()
}

const repoRoot = git('rev-parse', '--show-toplevel')
const candidates = positionals.length
    ? positionals
    : [
          ...git('diff', '--name-only', '--diff-filter=ACMR', '-z', `${values.base}...HEAD`).split('\0'),
          ...git('diff', '--name-only', '--diff-filter=ACMR', '-z', 'HEAD').split('\0'),
          ...git('ls-files', '--others', '--exclude-standard', '-z').split('\0'),
      ]
const files = [...new Set(candidates)]
    .filter(Boolean)
    .map((file) => (isAbsolute(file) ? file : resolve(repoRoot, file)))
    .filter((file) => {
        const name = relative(repoRoot, file)
        return (
            /^(frontend\/src\/|products\/[^/]+\/frontend\/).*\.[cm]?[jt]sx?$/.test(name) &&
            !name.split('/').includes('generated') &&
            existsSync(file)
        )
    })

if (files.length === 0) {
    console.info('No changed React source files to check.')
} else {
    const result = spawnSync(
        process.execPath,
        [
            resolve(toolRoot, 'node_modules/react-doctor/bin/react-doctor.js'),
            '--category',
            'Performance',
            '--no-supply-chain',
            '--no-score',
            '--blocking',
            'warning',
            '--verbose',
            '--yes',
            ...files,
        ],
        { cwd: repoRoot, stdio: 'inherit' }
    )
    if (result.error) {
        throw result.error
    }
    process.exitCode = result.status ?? 1
}
