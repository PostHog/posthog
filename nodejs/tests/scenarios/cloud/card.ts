import { loadText } from '../cards'
import { Origin } from './admission'

export const FAILOVER_VALVE = 'pg.failover'

export type RunCard = { id: string; failsOver: boolean }

const CARD_ID = /^[a-z0-9]+(-[a-z0-9]+)*$/

export function isCardId(id: string): boolean {
    return CARD_ID.test(id)
}

export function runCardOf(origin: Origin, commit: string, id: string, runnerProfile: Buffer): RunCard {
    const file = `nodejs/tests/scenarios/cards/${id}.yaml at ${commit}`
    let yaml: string
    try {
        yaml = origin.cardAt(commit, id)
    } catch (error) {
        throw new Error(`${id} is not a card at commit ${commit}: ${(error as Error).message}`)
    }
    const { card } = loadText(file, { card: yaml, profile: runnerProfile.toString('utf8') })
    return { id, failsOver: card.valves.some(({ valve }) => valve === FAILOVER_VALVE) }
}
