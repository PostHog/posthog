import Chance from 'chance'
import { once } from 'events'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import type { LoadedCard } from '../cards'
import { durationMs } from '../duration'
import type { FollowUpAnswer, Judge } from '../judge/judge'
import { OfferContext, SENDER, TRAFFIC, TrafficKind } from './traffic'

export type SeedState = { teamIds: number[]; flowIds: Record<string, Record<number, string>> }

const followUpFlowKey = (name: string): string => `${name}.followup`

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

const pause = (ms: number, signal: AbortSignal): Promise<void> =>
    new Promise((resolve) => {
        const done = (): void => {
            clearTimeout(timer)
            signal.removeEventListener('abort', done)
            resolve()
        }
        const timer = setTimeout(done, ms)
        signal.addEventListener('abort', done, { once: true })
    })

export async function seed({ card }: LoadedCard, postgres: PostgresRouter): Promise<SeedState> {
    const teamIds: number[] = []
    const flowIds: SeedState['flowIds'] = {}
    for (let i = 0; i < card.setup.teams; i++) {
        const { team } = await createTestTeamFixture(postgres)
        const integration = await insertIntegration(postgres, team.id, {
            kind: 'email',
            config: { ...SENDER, verified: true },
        })
        for (const { name } of card.drive.traffic) {
            const kind = trafficKind(name)
            const flows = [{ key: name, flow: kind.flow }]
            if (kind.followUp) {
                flows.push({ key: followUpFlowKey(name), flow: kind.followUp.flow })
            }
            for (const { key, flow } of flows) {
                const inserted = await insertHogFlow(postgres, await flow(team.id, integration.id))
                flowIds[key] = { ...flowIds[key], [team.id]: inserted.id }
            }
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
    const followUps: Promise<unknown>[] = []
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
        const flowIdOf = (key: string): string => {
            const flowId = seeded.flowIds[key]?.[teamId]
            if (flowId === undefined) {
                throw new Error(`Team ${teamId} has no seeded ${key} flow`)
            }
            return flowId
        }
        const flowId = flowIdOf(kind.name)
        const followUpFlowId = kind.followUp && flowIdOf(followUpFlowKey(kind.name))
        const unitId = `${context.runId}-${n + 1}`
        const offeredAt = Date.now()
        const offer = kind.offer({ unitId, teamId, flowId }, context).then(async (answer) => {
            const answeredAt = Date.now()
            let followUp: FollowUpAnswer | undefined
            if (kind.followUp && followUpFlowId !== undefined && answer.accepted && !stop.aborted) {
                const offered = kind.followUp.offer({ unitId, teamId, flowId: followUpFlowId }, context, stop)
                followUps.push(offered)
                followUp = await offered
            }
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
                ...(followUp && { followUp }),
            })
            if (kind.intake !== 'event' || (answer.accepted && answeredAt <= end)) {
                offeredUnits += 1
            }
        })
        offer.catch((error: unknown) => {
            if (!stop.aborted) {
                failed.abort(error)
            }
        })
        offers.push(offer)
    }
    await untilAborted(Promise.all(offers), stop)
    await Promise.allSettled(followUps)
    if (!stop.aborted && Date.now() < end) {
        await pause(end - Date.now(), stop)
    }
    if (failed.signal.aborted) {
        throw failed.signal.reason
    }
    return { targetUnits: schedule.length, offeredUnits }
}
