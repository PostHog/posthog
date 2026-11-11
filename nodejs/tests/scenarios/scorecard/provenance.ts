import { execFileSync } from 'child_process'
import { createHash } from 'crypto'
import os from 'os'
import path from 'path'

export const SCENARIOS_DIR = path.join(__dirname, '..')
const GENERATOR_DIR = 'generator'
const VALVES_DIR = 'valves'
const EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

export type Provenance = {
    headSha: string
    headDirty: boolean
    runnerVersion: string
    generatorVersion: string
    valvesVersion: string
    hostCpu: string
    hostMemoryGb: number
}

type TreeEntry = { mode: string; sha: string; name: string }

function git(cwd: string, args: string[]): string {
    return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
}

function entriesOf(scenariosDir: string): TreeEntry[] {
    return git(scenariosDir, ['ls-tree', '-z', '--full-tree', 'HEAD:./'])
        .split('\0')
        .filter((line) => line !== '')
        .map((line) => {
            const [meta, name] = line.split('\t')
            const [mode, , sha] = meta.split(' ')
            return { mode, sha, name }
        })
}

function treeHash(entries: TreeEntry[]): string {
    const body = Buffer.concat(
        entries.map(({ mode, sha, name }) =>
            Buffer.concat([Buffer.from(`${mode.replace(/^0+/, '')} ${name}\0`), Buffer.from(sha, 'hex')])
        )
    )
    return createHash('sha1')
        .update(Buffer.concat([Buffer.from(`tree ${body.length}\0`), body]))
        .digest('hex')
}

export function provenanceOf(scenariosDir: string = SCENARIOS_DIR): Provenance {
    const entries = entriesOf(scenariosDir)
    const versionOf = (dir: string): string => entries.find(({ name }) => name === dir)?.sha ?? EMPTY_TREE
    const cpus = os.cpus()
    return {
        headSha: git(scenariosDir, ['rev-parse', 'HEAD']).trim(),
        headDirty: git(scenariosDir, ['status', '--porcelain', '--', path.join(scenariosDir, '..', '..')]) !== '',
        runnerVersion: treeHash(entries.filter(({ name }) => name !== GENERATOR_DIR && name !== VALVES_DIR)),
        generatorVersion: versionOf(GENERATOR_DIR),
        valvesVersion: versionOf(VALVES_DIR),
        hostCpu: `${cpus[0]?.model.trim() ?? 'unknown'} x ${cpus.length}`,
        hostMemoryGb: Math.round(os.totalmem() / 1024 ** 3),
    }
}
