import { readdirSync } from 'fs'
import path from 'path'

import { CardError, load, stepsOf } from '../cards'
import { durationMs } from '../duration'
import { TRAFFIC } from '../generator/traffic'
import type { JournalEntry } from '../judge/judge'

export const CARDS_DIR = path.join(__dirname, '..', 'cards')

// Cards that only judge on a run host: the failover valve and the writer CPU bar read the run
// manifest, so a local run of them is `invalid` by design.
const RUN_HOST_VALVES = ['pg.failover']
const RUN_HOST_BARS = ['writer_cpu_under']

export type CardValve = {
    valve: string
    target: string
    dose: Record<string, unknown>
    atMs: number | null
    when: { queue: string; atLeast: number } | null
    forMs: number
}

export type CardView = {
    id: string
    file: string
    problems: string[]
    version?: number
    cardHash?: string
    profileName?: string
    seed?: number
    teams?: number
    driveMs?: number
    convergeWithinMs?: number
    minOffered?: number
    traffic?: { name: string; ratePerSecond: number | null; intake: JournalEntry['kind'] | null }[]
    steps?: { scale: number; fromMs: number; toMs: number }[]
    valves?: CardValve[]
    invariants?: { name: string; gate: number | null }[]
    measure?: string[]
    bars?: { name: string; params: Record<string, unknown> }[]
    runHostOnly?: boolean
}

const rateOf = (traffic: Record<string, unknown>, name: string): number | null => {
    const rate = (traffic[name] as { ratePerSecond?: unknown } | undefined)?.ratePerSecond
    return typeof rate === 'number' ? rate : null
}

export function cardViewOf(file: string): CardView {
    const id = path.basename(file, '.yaml')
    let loaded: ReturnType<typeof load>
    try {
        loaded = load(file)
    } catch (error) {
        return { id, file, problems: error instanceof CardError ? error.problems : [(error as Error).message] }
    }
    const { card, profile, cardHash } = loaded
    return {
        id: card.id,
        file,
        problems: [],
        version: card.version,
        cardHash,
        profileName: profile.name,
        seed: card.seed,
        teams: card.setup.teams,
        driveMs: durationMs(card.drive.for),
        convergeWithinMs: durationMs(card.convergeWithin),
        minOffered: card.drive.minOffered,
        traffic: card.drive.traffic.map(({ name }) => ({
            name,
            ratePerSecond: rateOf(profile.traffic, name),
            intake: TRAFFIC.find((kind) => kind.name === name)?.intake ?? null,
        })),
        steps: stepsOf(card.drive),
        valves: card.valves.map((entry) => ({
            valve: entry.valve,
            target: entry.target,
            dose: entry.dose,
            atMs: entry.at === undefined ? null : durationMs(entry.at),
            when: entry.when === undefined ? null : entry.when.params,
            forMs: durationMs(entry.for),
        })),
        invariants: card.invariants.map(({ name }) => ({ name, gate: card.gates[name] ?? null })),
        measure: card.measure.map(({ name }) => name),
        bars: card.bars.map(({ name, params }) => ({ name, params })),
        runHostOnly:
            card.valves.some(({ valve }) => RUN_HOST_VALVES.includes(valve)) ||
            card.bars.some(({ name }) => RUN_HOST_BARS.includes(name)),
    }
}

export function catalogOf(cardsDir: string = CARDS_DIR): CardView[] {
    return readdirSync(cardsDir)
        .filter((name) => name.endsWith('.yaml'))
        .sort()
        .map((name) => cardViewOf(path.join(cardsDir, name)))
}
