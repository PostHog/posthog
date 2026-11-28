import { loadText } from '../cards'
import type { ReadAlertFile } from '../cards/load'
import { pairProblemsOf } from '../runner/pair'
import { FailoverDose } from '../valves/valves'
import { Origin } from './admission'

export const FAILOVER_VALVE = 'pg.failover'

export type RunCard = {
    id: string
    failsOver: boolean
    warmReader?: true
    seed?: number
    pair?: { drive: string; convergeWithin: string }
}

const CARD_ID = /^[a-z0-9]+(-[a-z0-9]+)*$/

export function isCardId(id: string): boolean {
    return CARD_ID.test(id)
}

export function runCardOf(
    origin: Origin,
    commit: string,
    id: string,
    runnerProfile: Buffer,
    readAlertFile: ReadAlertFile,
    seed?: number
): RunCard {
    const file = `nodejs/tests/scenarios/cards/${id}.yaml at ${commit}`
    let yaml: string
    try {
        yaml = origin.cardAt(commit, id)
    } catch (error) {
        throw new Error(`${id} is not a card at commit ${commit}: ${(error as Error).message}`)
    }
    const loaded = loadText(file, { card: yaml, profile: runnerProfile.toString('utf8') }, { seed, readAlertFile })
    const { card } = loaded
    const [problem] = card.pair ? pairProblemsOf(loaded, true) : []
    if (problem !== undefined) {
        throw new Error(problem)
    }
    const warmReaders = card.valves
        .filter(({ valve }) => valve === FAILOVER_VALVE)
        .map(({ dose }) => FailoverDose.parse(dose).warmReader === true)
    if (new Set(warmReaders).size > 1) {
        throw new Error(`${id} fails the reader over both with and without warmReader`)
    }
    return {
        id,
        failsOver: warmReaders.length > 0,
        ...(warmReaders.includes(true) && { warmReader: true }),
        ...(seed !== undefined && { seed }),
        ...(card.pair && { pair: { drive: card.drive.for, convergeWithin: card.convergeWithin } }),
    }
}
