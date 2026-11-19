import Chance from 'chance'
import { once } from 'events'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { LoadedCard, stepsOf } from '../cards'
import { pause } from '../duration'
import type { FollowUpAnswer, Judge } from '../judge/judge'
import { OfferContext, SENDER, TRAFFIC, TrafficKind } from './traffic'

export type SeedState = { teamIds: number[]; flowIds: Record<string, Record<number, string>> }

const followUpFlowKey = (name: string): string => `${name}.followup`

export type DrivenStep = {
    index: number
    scale: number
    startedAt: number
    endedAt: number
    dueUnits: number
    offeredUnits: number
    waitedFor?: number
}

export type DriveSummary = { targetUnits: number; offeredUnits: number; steps: DrivenStep[] }

export type StepWindow = Omit<DrivenStep, 'offeredUnits' | 'waitedFor'>

export type StepGate = (step: StepWindow, offered: () => number) => Promise<void>

export type DriveContext = OfferContext & { runId: string; halt?: AbortSignal; gate?: StepGate }

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

export async function seed(
    { card, profile }: LoadedCard,
    postgres: PostgresRouter,
    signal: AbortSignal
): Promise<SeedState> {
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
            const kind = trafficKind(name)
            const { parks } = kind.profile.parse(profile.traffic[name])
            const flows = [{ key: name, flow: kind.flow }]
            if (kind.followUp) {
                flows.push({ key: followUpFlowKey(name), flow: kind.followUp.flow })
            }
            for (const { key, flow } of flows) {
                const inserted = await insertHogFlow(postgres, await flow(team.id, integration.id, parks))
                flowIds[key] = { ...flowIds[key], [team.id]: inserted.id }
            }
        }
        teamIds.push(team.id)
    }
    return { teamIds, flowIds }
}

type Slot = { kind: TrafficKind; atMs: number }

function stepScheduleOf({ card, profile }: Pick<LoadedCard, 'card' | 'profile'>): Slot[][] {
    const kinds = card.drive.traffic.map(({ name }) => {
        const kind = trafficKind(name)
        return { kind, ratePerSecond: kind.profile.parse(profile.traffic[name]).ratePerSecond }
    })
    return stepsOf(card.drive).map(({ scale, fromMs, toMs }) =>
        kinds
            .flatMap(({ kind, ratePerSecond }) => {
                const rate = ratePerSecond * scale
                const units = Math.round((rate * (toMs - fromMs)) / 1000)
                return Array.from({ length: units }, (_, i) => ({ kind, atMs: (i * 1000) / rate }))
            })
            .sort((a, b) => a.atMs - b.atMs)
    )
}

export async function drive(
    { card, profile }: LoadedCard,
    seeded: SeedState,
    journal: Pick<Judge, 'record'>,
    signal: AbortSignal,
    context: DriveContext
): Promise<DriveSummary> {
    const planned = stepsOf(card.drive)
    const schedules = stepScheduleOf({ card, profile })
    const chance = new Chance(card.seed)
    let attempted = 0
    const counted: { step: DrivenStep; answeredAt: number }[] = []
    const answeredAts = new Map<DrivenStep, number[]>()
    const steps: DrivenStep[] = []
    const offers: Promise<void>[] = []
    const followUps: Promise<unknown>[] = []
    const failed = new AbortController()
    const stop = AbortSignal.any([signal, failed.signal])
    const halted = context.halt ? AbortSignal.any([stop, context.halt]) : stop

    const offerUnit = (kind: TrafficKind, step: DrivenStep): void => {
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
        attempted += 1
        const unitId = `${context.runId}-${attempted}`
        const offeredAt = Date.now()
        if (kind.intake !== 'event') {
            answeredAts.get(step)?.push(-Infinity)
        }
        const offer = kind.offer({ unitId, teamId, flowId }, context).then(async (answer) => {
            const answeredAt = kind.intake === 'event' ? Date.now() : -Infinity
            const counts = kind.intake !== 'event' || answer.accepted
            if (stop.aborted) {
                return
            }
            if (counts && kind.intake === 'event') {
                answeredAts.get(step)?.push(answeredAt)
            }
            let followUp: FollowUpAnswer | undefined
            if (kind.followUp && followUpFlowId !== undefined && answer.accepted) {
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
                step: step.index,
                answer,
                expect: { deliveries: kind.deliveries },
                ...(followUp && { followUp }),
            })
            if (counts) {
                counted.push({ step, answeredAt })
            }
        })
        offer.catch((error: unknown) => {
            if (!stop.aborted) {
                failed.abort(error)
            }
        })
        offers.push(offer)
    }

    const offerSlots = async (
        slots: Slot[],
        fromAt: number,
        until: AbortSignal,
        step: DrivenStep,
        late: (now: number) => boolean
    ): Promise<number> => {
        let sent = 0
        for (const { kind, atMs } of slots) {
            const waitMs = fromAt + atMs - Date.now()
            if (waitMs > 0) {
                await untilAborted(elapse(waitMs), until)
            }
            if (until.aborted || late(Date.now())) {
                return sent
            }
            offerUnit(kind, step)
            sent += 1
        }
        return sent
    }

    const fixedSteps = card.drive.stopOnBreak === true
    const judged: { settled: boolean; done: Promise<void> }[] = []
    const driveStartedAt = Date.now()
    const driveEnd = driveStartedAt + (planned.at(-1)?.toMs ?? 0)
    let stretchedMs = 0
    for (const [index, { scale, fromMs, toMs }] of planned.entries()) {
        if (halted.aborted) {
            break
        }
        const startedAt = driveStartedAt + fromMs + stretchedMs
        const lastsMs = toMs - fromMs
        const step: DrivenStep = { index, scale, startedAt, endedAt: startedAt + lastsMs, dueUnits: 0, offeredUnits: 0 }
        steps.push(step)
        if (context.gate !== undefined) {
            answeredAts.set(step, [])
        }
        const slots = schedules[index]
        const late = fixedSteps ? (now: number) => now >= step.endedAt : (now: number) => now > driveEnd
        let sent = await offerSlots(slots, startedAt, halted, step, late)
        while (!halted.aborted && Date.now() < step.endedAt) {
            await pause(step.endedAt - Date.now(), halted)
        }
        if (halted.aborted) {
            step.endedAt = Math.min(step.endedAt, Date.now())
        }
        const previous = judged[index - 1]
        if (fixedSteps && previous && !previous.settled && !halted.aborted && index < planned.length - 1) {
            step.waitedFor = index - 1
            const verdict = new AbortController()
            void previous.done.finally(() => verdict.abort())
            const until = AbortSignal.any([halted, verdict.signal])
            for (let cycle = 1; !until.aborted; cycle++) {
                const cycleAt = startedAt + cycle * lastsMs
                sent += await offerSlots(slots, cycleAt, until, step, (now) => now >= cycleAt + lastsMs)
                await pause(cycleAt + lastsMs - Date.now(), until)
            }
            step.endedAt = Date.now()
            stretchedMs += step.endedAt - (startedAt + lastsMs)
        }
        const cycles = Math.max(1, Math.ceil((step.endedAt - startedAt) / lastsMs))
        step.dueUnits = Math.max(
            sent,
            Array.from({ length: cycles }, (_, cycle) => startedAt + cycle * lastsMs).reduce(
                (due, cycleAt) => due + slots.filter(({ atMs }) => cycleAt + atMs < step.endedAt).length,
                0
            )
        )
        if (halted.aborted || context.gate === undefined || index === planned.length - 1) {
            continue
        }
        const window = { index, scale, startedAt, endedAt: step.endedAt, dueUnits: step.dueUnits }
        const entry = { settled: false, done: Promise.resolve() }
        entry.done = context
            .gate(window, () => answeredAts.get(step)!.filter((answeredAt) => answeredAt <= step.endedAt).length)
            .catch((error: unknown) => failed.abort(error))
            .finally(() => (entry.settled = true))
        judged[index] = entry
    }
    const stoppedEarly = halted.aborted && !stop.aborted
    const end = steps.at(-1)?.endedAt ?? -Infinity
    try {
        await untilAborted(Promise.all(offers), stop)
    } finally {
        await Promise.allSettled(followUps)
    }
    if (failed.signal.aborted) {
        throw failed.signal.reason
    }
    let offeredUnits = 0
    for (const { step, answeredAt } of counted) {
        if (answeredAt <= (fixedSteps ? step.endedAt : end)) {
            step.offeredUnits += 1
            offeredUnits += 1
        }
    }
    const targetUnits =
        stoppedEarly || fixedSteps ? steps.reduce((sum, { dueUnits }) => sum + dueUnits, 0) : schedules.flat().length
    return { targetUnits, offeredUnits, steps }
}
