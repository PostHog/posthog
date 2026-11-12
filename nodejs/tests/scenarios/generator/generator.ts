import Chance from 'chance'
import { once } from 'events'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import type { LoadedCard } from '../cards'
import { durationMs } from '../duration'
import type { Judge } from '../judge/judge'
import { OfferContext, SENDER, TRAFFIC, TrafficKind } from './traffic'

export type SeedState = { teamIds: number[]; flowIds: Record<string, Record<number, string>> }

export type DriveSummary = { targetUnits: number; offeredUnits: number }

export type DriveContext = OfferContext & { runId: string }

function trafficKind(name: string): TrafficKind {
    const kind = TRAFFIC.find((traffic) => traffic.name === name)
    if (!kind) {
        throw new Error(`No traffic kind ${name}`)
    }
    return kind
}

async function untilAborted(work: Promise<unknown>, signal: AbortSignal): Promise<void> {
    if (signal.aborted) {
        work.catch(() => undefined)
        return
    }
    const settled = new AbortController()
    try {
        await Promise.race([work, once(signal, 'abort', { signal: settled.signal })])
    } finally {
        settled.abort()
    }
}

const elapse = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export async function seed({ card }: LoadedCard, postgres: PostgresRouter, signal: AbortSignal): Promise<SeedState> {
    const teamIds: number[] = []
    const flowIds: SeedState['flowIds'] = {}
    for (let i = 0; i < card.setup.teams; i++) {
        signal.throwIfAborted()
        const { team } = await createTestTeamFixture(postgres)
        const integration = await insertIntegration(postgres, team.id, {
            kind: 'email',
            config: { ...SENDER, verified: true },
        })
        for (const { name } of card.drive.traffic) {
            signal.throwIfAborted()
            const flow = await insertHogFlow(postgres, await trafficKind(name).flow(team.id, integration.id))
            flowIds[name] = { ...flowIds[name], [team.id]: flow.id }
        }
        teamIds.push(team.id)
    }
    return { teamIds, flowIds }
}

export async function drive(
    { card, profile }: LoadedCard,
    seeded: SeedState,
    journal: Pick<Judge, 'record'>,
    signal: AbortSignal,
    context: DriveContext
): Promise<DriveSummary> {
    const forMs = durationMs(card.drive.for)
    const schedule = card.drive.traffic
        .flatMap(({ name }) => {
            const kind = trafficKind(name)
            const { ratePerSecond } = kind.profile.parse(profile.traffic[name])
            const units = Math.round((ratePerSecond * forMs) / 1000)
            return Array.from({ length: units }, (_, i) => ({ kind, atMs: (i * 1000) / ratePerSecond }))
        })
        .sort((a, b) => a.atMs - b.atMs)
    const chance = new Chance(card.seed)
    const start = Date.now()
    const end = start + forMs
    let offeredUnits = 0
    const offers: Promise<void>[] = []
    const failed = new AbortController()
    const stop = AbortSignal.any([signal, failed.signal])
    for (const [n, { kind, atMs }] of schedule.entries()) {
        const waitMs = start + atMs - Date.now()
        if (waitMs > 0) {
            await untilAborted(elapse(waitMs), stop)
        }
        if (stop.aborted || Date.now() > end) {
            break
        }
        const teamId = chance.pickone(seeded.teamIds)
        const flowId = seeded.flowIds[kind.name]?.[teamId]
        if (flowId === undefined) {
            throw new Error(`Team ${teamId} has no seeded ${kind.name} flow`)
        }
        const unitId = `${context.runId}-${n + 1}`
        const offeredAt = Date.now()
        const offer = kind.offer({ unitId, teamId, flowId }, context).then((answer) => {
            if (stop.aborted) {
                return
            }
            journal.record({
                unitId,
                kind: kind.intake,
                teamId,
                offeredAt,
                answer,
                expect: { deliveries: kind.deliveries },
            })
            if (kind.intake !== 'event' || (answer.accepted && Date.now() <= end)) {
                offeredUnits += 1
            }
        })
        offer.catch((error: unknown) => failed.abort(error))
        offers.push(offer)
    }
    await untilAborted(Promise.all(offers), stop)
    if (failed.signal.aborted) {
        throw failed.signal.reason
    }
    return { targetUnits: schedule.length, offeredUnits }
}
