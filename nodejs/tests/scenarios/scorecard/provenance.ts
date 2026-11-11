import { execFileSync } from 'child_process'
import os from 'os'
import path from 'path'

export const SCENARIOS_DIR = path.join(__dirname, '..')
const GENERATOR_DIR = 'generator'
const VALVES_DIR = 'valves'
const DATA_DIRS = ['cards', 'profiles']
const DATA_FILE = /\.yaml$/
const EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

export type Provenance = {
    headSha: string | null
    headDirty: boolean | null
    runnerVersion: string | null
    generatorVersion: string | null
    valvesVersion: string | null
    hostCpu: string
    hostMemoryGb: number
}

type GitProvenance = Pick<Provenance, 'headSha' | 'headDirty' | 'runnerVersion' | 'generatorVersion' | 'valvesVersion'>

function git(cwd: string, args: string[], input = ''): string {
    return execFileSync('git', args, { cwd, input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] })
}

function known<T>(read: () => T): T | null {
    try {
        return read()
    } catch {
        return null
    }
}

type TreeEntry = { line: string; name: string; sha: string }

function entriesOf(scenariosDir: string, tree: string): TreeEntry[] {
    return git(scenariosDir, ['ls-tree', '-z', '--full-tree', tree])
        .split('\0')
        .filter((line) => line !== '')
        .map((line) => {
            const [meta, name] = line.split('\t')
            return { line, name, sha: meta.split(' ')[2] }
        })
}

function mktree(scenariosDir: string, entries: TreeEntry[]): string {
    return git(scenariosDir, ['mktree', '-z'], entries.map(({ line }) => `${line}\0`).join('')).trim()
}

function runnerTreeOf(scenariosDir: string, entries: TreeEntry[]): string {
    const codeEntry = (entry: TreeEntry): TreeEntry => {
        const code = entriesOf(scenariosDir, entry.sha).filter(({ name }) => !DATA_FILE.test(name))
        return { ...entry, line: `040000 tree ${mktree(scenariosDir, code)}\t${entry.name}` }
    }
    return mktree(
        scenariosDir,
        entries
            .filter(({ name }) => name !== GENERATOR_DIR && name !== VALVES_DIR)
            .map((entry) => (DATA_DIRS.includes(entry.name) ? codeEntry(entry) : entry))
    )
}

function gitProvenanceOf(scenariosDir: string): GitProvenance {
    const entries = known(() => entriesOf(scenariosDir, 'HEAD:./'))
    const versionOf = (dir: string): string | null =>
        entries && (entries.find(({ name }) => name === dir)?.sha ?? EMPTY_TREE)
    return {
        headSha: known(() => git(scenariosDir, ['rev-parse', 'HEAD']).trim()),
        headDirty: known(
            () => git(scenariosDir, ['status', '--porcelain', '--', path.join(scenariosDir, '..', '..')]) !== ''
        ),
        runnerVersion: entries && known(() => runnerTreeOf(scenariosDir, entries)),
        generatorVersion: versionOf(GENERATOR_DIR),
        valvesVersion: versionOf(VALVES_DIR),
    }
}

export function provenanceOf(scenariosDir: string = SCENARIOS_DIR): Provenance {
    const cpus = os.cpus()
    return {
        ...gitProvenanceOf(scenariosDir),
        hostCpu: `${cpus[0]?.model.trim() ?? 'unknown'} x ${cpus.length}`,
        hostMemoryGb: Math.round(os.totalmem() / 1024 ** 3),
    }
}
