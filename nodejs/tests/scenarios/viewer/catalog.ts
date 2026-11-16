import { readdirSync } from 'fs'
import path from 'path'

import { CardError, load, stepsOf } from '../cards'
import { durationMs } from '../duration'
import { TRAFFIC } from '../generator/traffic'
import { BARS } from '../judge/bars'
import type { JournalEntry } from '../judge/judge'
import { VALVES } from '../valves/valves'

export const CARDS_DIR = path.join(__dirname, '..', 'cards')

export type CardValve = {
    valve: string
    target: string
    dose: Record<string, unknown>
    atMs: number | null
    when: { queue: string; atLeast: number } | null
    forMs: number
}

export type CardBar = { name: string; params: Record<string, unknown>; unit: string }

export type BrokenCard = { ok: false; id: string; file: string; problems: string[] }

export type LoadedCard = {
    ok: true
    id: string
    file: string
    version: number
    cardHash: string
    profileName: string
    seed: number
    teams: number
    driveMs: number
    convergeWithinMs: number
    minOffered: number
    traffic: { name: string; ratePerSecond: number | null; intake: JournalEntry['kind'] | null }[]
    steps: { scale: number; fromMs: number; toMs: number }[]
    valves: CardValve[]
    invariants: { name: string; gate: number | null }[]
    measure: string[]
    bars: CardBar[]
    runHostOnly: boolean
}

export type CardView = BrokenCard | LoadedCard

const rateOf = (traffic: Record<string, unknown>, name: string): number | null => {
    const rate = (traffic[name] as { ratePerSecond?: unknown } | undefined)?.ratePerSecond
    return typeof rate === 'number' ? rate : null
}

const valveNeedsRunHost = (name: string): boolean => VALVES.some((valve) => valve.name === name && valve.needsRunHost)

const barOf = (name: string): (typeof BARS)[number] | undefined => BARS.find((bar) => bar.name === name)

export function cardViewOf(file: string): CardView {
    const id = path.basename(file, '.yaml')
    let loaded: ReturnType<typeof load>
    try {
        loaded = load(file)
    } catch (error) {
        return {
            ok: false,
            id,
            file,
            problems: error instanceof CardError ? error.problems : [(error as Error).message],
        }
    }
    const { card, profile, cardHash } = loaded
    return {
        ok: true,
        id: card.id,
        file,
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
        bars: card.bars.map(({ name, params }) => ({ name, params, unit: barOf(name)?.unit ?? '' })),
        runHostOnly:
            card.valves.some(({ valve }) => valveNeedsRunHost(valve)) ||
            card.bars.some(({ name }) => barOf(name)?.needsRunHost === true),
    }
}

export function catalogOf(cardsDir: string): CardView[] {
    return readdirSync(cardsDir)
        .filter((name) => name.endsWith('.yaml'))
        .sort()
        .map((name) => cardViewOf(path.join(cardsDir, name)))
}
