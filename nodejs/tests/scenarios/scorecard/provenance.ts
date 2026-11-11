import { execFileSync } from 'child_process'
import os from 'os'
import path from 'path'

export const SCENARIOS_DIR = path.join(__dirname, '..')
const GENERATOR_DIR = 'generator'
const VALVES_DIR = 'valves'
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

function gitProvenanceOf(scenariosDir: string): GitProvenance {
    const entries = known(() =>
        git(scenariosDir, ['ls-tree', '-z', '--full-tree', 'HEAD:./'])
            .split('\0')
            .filter((line) => line !== '')
            .map((line) => {
                const [meta, name] = line.split('\t')
                return { line, name, sha: meta.split(' ')[2] }
            })
    )
    const versionOf = (dir: string): string | null =>
        entries && (entries.find(({ name }) => name === dir)?.sha ?? EMPTY_TREE)
    const runnerEntries = entries && entries.filter(({ name }) => name !== GENERATOR_DIR && name !== VALVES_DIR)
    return {
        headSha: known(() => git(scenariosDir, ['rev-parse', 'HEAD']).trim()),
        headDirty: known(
            () => git(scenariosDir, ['status', '--porcelain', '--', path.join(scenariosDir, '..', '..')]) !== ''
        ),
        runnerVersion:
            runnerEntries &&
            known(() =>
                git(scenariosDir, ['mktree', '-z'], runnerEntries.map(({ line }) => `${line}\0`).join('')).trim()
            ),
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
