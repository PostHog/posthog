import { z } from 'zod'

import { Duration } from '../duration'

export const CdpRole = z.enum([
    'cdp-processed-events',
    'cdp-cyclotron-worker-hogflow',
    'cdp-cyclotron-worker-email',
    'cdp-api',
    'cdp-cyclotron-v2-janitor',
])

export const Named = z.object({ name: z.string(), params: z.record(z.string(), z.unknown()).default({}) }).strict()
export type Named = z.infer<typeof Named>

export const RunningOnQueue = z
    .object({
        name: z.literal('running_on_queue', { error: 'running_on_queue is the only predicate' }),
        params: z.object({ queue: z.string(), atLeast: z.number().int().min(1) }).strict(),
    })
    .strict()

export const ValveEntry = z
    .object({
        valve: z.string(),
        target: z.string(),
        dose: z.record(z.string(), z.unknown()),
        at: Duration.optional(),
        when: RunningOnQueue.optional(),
        for: Duration,
    })
    .strict()
    .refine((entry) => (entry.at === undefined) !== (entry.when === undefined), 'exactly one of at, when')
export type ValveEntry = z.infer<typeof ValveEntry>

export const Card = z
    .object({
        id: z.string(),
        version: z.number().int(),
        clock: z.literal('real'),
        profile: z.string(),
        seed: z.number().int(),
        setup: z.object({ teams: z.number().int().min(1) }).strict(),
        drive: z
            .object({
                for: Duration,
                traffic: z.array(Named).min(1),
                minOffered: z.number().min(0).max(1).default(0.9),
            })
            .strict(),
        valves: z.array(ValveEntry).default([]),
        convergeWithin: Duration,
        invariants: z.array(Named).min(1),
        measure: z.array(Named).default([]),
        gates: z.record(z.string(), z.number()).default({}),
    })
    .strict()
export type Card = z.infer<typeof Card>

export const Profile = z
    .object({
        name: z.string(),
        traffic: z.record(z.string(), z.unknown()).default({}),
        settings: z.record(z.string(), z.string()).default({}),
    })
    .strict()
export type Profile = z.infer<typeof Profile>
