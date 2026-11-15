import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

import { load } from '../cards'
import { Origin } from './admission'

export const FAILOVER_VALVE = 'pg.failover'

export type RunCard = { id: string; failsOver: boolean }

const CARD_ID = /^[a-z0-9]+(-[a-z0-9]+)*$/

export function isCardId(id: string): boolean {
    return CARD_ID.test(id)
}

export function runCardOf(origin: Origin, commit: string, id: string, runnerProfile: Buffer): RunCard {
    let yaml: string
    try {
        yaml = origin.cardAt(commit, id)
    } catch (error) {
        throw new Error(`${id} is not a card at commit ${commit}: ${(error as Error).message}`)
    }
    const dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-card-'))
    try {
        const cardPath = path.join(dir, `${id}.yaml`)
        const profilePath = path.join(dir, 'runner-profile.yaml')
        writeFileSync(cardPath, yaml)
        writeFileSync(profilePath, runnerProfile)
        const { card } = load(cardPath, { profilePath })
        return { id, failsOver: card.valves.some(({ valve }) => valve === FAILOVER_VALVE) }
    } finally {
        rmSync(dir, { recursive: true, force: true })
    }
}
