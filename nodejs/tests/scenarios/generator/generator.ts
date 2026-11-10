import { setTimeout as sleep } from 'timers/promises'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import type { LoadedCard } from '../cards'
import { durationMs } from '../duration'
import type { Judge } from '../judge/judge'
import { OfferContext, SENDER, TRAFFIC, TrafficKind } from './traffic'

export type SeedState = {
    teams: { teamId: number; emailIntegrationId: number }[]
    flows: { teamId: number; flowId: string; deliveryActions: string[] }[]
}

export type DriveSummary = { targetUnits: number; offeredUnits: number }

export type DriveContext = OfferContext & { runId: string }

function trafficKind(name: string): TrafficKind {
    const kind = TRAFFIC.find((traffic) => traffic.name === name)
    if (!kind) {
        throw new Error(`No traffic kind ${name}`)
    }
    return kind
}

function seededRandom(seed: number): () => number {
    let state = seed >>> 0
    return () => {
        state = (state + 0x6d2b79f5) >>> 0
        let mixed = Math.imul(state ^ (state >>> 15), state | 1)
        mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61)
        return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296
    }
}

export async function seed({ card }: LoadedCard, postgres: PostgresRouter): Promise<SeedState> {
    const state: SeedState = { teams: [], flows: [] }
    for (let i = 0; i < card.setup.teams; i++) {
        const { team } = await createTestTeamFixture(postgres)
        const integration = await insertIntegration(postgres, team.id, {
            kind: 'email',
            config: { ...SENDER, verified: true },
        })
        state.teams.push({ teamId: team.id, emailIntegrationId: integration.id })
        for (const { name } of card.drive.traffic) {
            const kind = trafficKind(name)
            const flow = await insertHogFlow(postgres, await kind.flow(team.id, integration.id))
            state.flows.push({ teamId: team.id, flowId: flow.id, deliveryActions: kind.deliveries })
        }
    }
    return state
}

export async function drive(
    { card, profile }: LoadedCard,
    seeded: SeedState,
    journal: Pick<Judge, 'record'>,
    signal: AbortSignal,
    context: DriveContext
): Promise<DriveSummary> {
    const forMs = durationMs(card.drive.for)
    const random = seededRandom(card.seed)
    const schedule = card.drive.traffic
        .flatMap(({ name }) => {
            const kind = trafficKind(name)
            const { ratePerSecond } = kind.profile.parse(profile.traffic[name])
            const units = Math.round((ratePerSecond * forMs) / 1000)
            return Array.from({ length: units }, (_, i) => ({ kind, atMs: (i * 1000) / ratePerSecond }))
        })
        .sort((a, b) => a.atMs - b.atMs)
    const start = Date.now()
    const offers: Promise<void>[] = []
    for (const [n, { kind, atMs }] of schedule.entries()) {
        await sleep(Math.max(0, start + atMs - Date.now()), undefined, { signal }).catch(() => undefined)
        if (signal.aborted || Date.now() > start + forMs) {
            break
        }
        const { teamId } = seeded.teams[Math.floor(random() * seeded.teams.length)]
        const unitId = `${context.runId}-${n + 1}`
        const offeredAt = Date.now()
        offers.push(
            kind.offer({ unitId, teamId }, context).then((answer) =>
                journal.record({
                    unitId,
                    kind: kind.intake,
                    teamId,
                    offeredAt,
                    answer,
                    expect: { deliveries: kind.deliveries },
                })
            )
        )
    }
    await Promise.all(offers)
    return { targetUnits: schedule.length, offeredUnits: offers.length }
}
