import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'

import { CyclotronV2JobInit } from '../services/cyclotron-v2/types'

export const INTAKE_MESSAGE_VERSION = 1

// Leaves room under the topics' 2 MB max.message.bytes for the key, the headers and the record overhead.
export const INTAKE_MESSAGE_MAX_BYTES = 1.5 * 1024 * 1024

export const RUN_KINDS = ['transactional-email', 'workflow-webhook'] as const
export type RunKind = (typeof RUN_KINDS)[number]

export type IntakeDeadLetterReason = 'not_json' | 'schema_invalid'

// Each field is held to its cyclotron column, because a value the row refuses fails the whole insert batch.
const PG_INT_MAX = 2 ** 31 - 1
const PG_SMALLINT_MAX = 2 ** 15 - 1
// Any hex UUID, as Postgres takes. Run ids from UUIDT set no RFC version or variant bits, so z.uuid() refuses them.
const pgUuid = z.guid()
const pgText = z.string().refine((value) => !value.includes('\u0000'), { message: 'text cannot hold a NUL character' })

// Objects stay loose, so a consumer still reads a message that a newer producer of the same version extends.
const IntakeJobStateSchema = z.looseObject({
    state: z
        .looseObject({
            acceptedAt: z.iso.datetime().optional(),
            sendBy: z.iso.datetime().optional(),
        })
        .nullable(),
})

const IntakeJobSchema = z.looseObject({
    id: pgUuid,
    functionId: pgUuid.nullable(),
    queueName: pgText.min(1),
    priority: z
        .number()
        .int()
        .min(-PG_SMALLINT_MAX - 1)
        .max(PG_SMALLINT_MAX),
    scheduled: z.iso.datetime(),
    parentRunId: pgText.nullable(),
    distinctId: pgText.nullable(),
    personId: pgText.nullable(),
    actionId: pgText.nullable(),
    // The same JSON the cyclotron row stores as bytes, kept as an object so the message stays readable.
    state: IntakeJobStateSchema.nullable(),
})

const IntakeMessageSchema = z.looseObject({
    v: z.literal(INTAKE_MESSAGE_VERSION),
    kind: z.enum(RUN_KINDS),
    teamId: z.number().int().positive().max(PG_INT_MAX),
    // Present when the caller sent an idempotency key. The key and its scope stay with the route.
    fingerprint: pgText.min(1).optional(),
    job: IntakeJobSchema,
})

export type IntakeMessage = z.infer<typeof IntakeMessageSchema>

export type IntakeRun = {
    kind: RunKind
    fingerprint?: string
    job: CyclotronV2JobInit & { id: string }
}

export type EncodedIntakeMessage = {
    key: string
    value: Buffer
    headers: Record<string, string>
}

export type EncodeResult = { status: 'encoded'; message: EncodedIntakeMessage } | { status: 'too_large'; bytes: number }

export type DecodeResult =
    | { status: 'decoded'; message: IntakeMessage }
    | { status: 'dead_letter'; reason: IntakeDeadLetterReason }

export function encodeIntakeMessage({ kind, fingerprint, job }: IntakeRun): EncodeResult {
    const message: IntakeMessage = {
        v: INTAKE_MESSAGE_VERSION,
        kind,
        teamId: job.teamId,
        ...(fingerprint !== undefined && { fingerprint }),
        job: {
            id: job.id,
            functionId: job.functionId ?? null,
            queueName: job.queueName,
            priority: job.priority ?? 0,
            scheduled: (job.scheduled ?? new Date()).toISOString(),
            parentRunId: job.parentRunId ?? null,
            distinctId: job.distinctId ?? null,
            personId: job.personId ?? null,
            actionId: job.actionId ?? null,
            state: job.state ? parseJSON(job.state.toString('utf-8')) : null,
        },
    }
    const value = Buffer.from(JSON.stringify(message))
    if (value.length > INTAKE_MESSAGE_MAX_BYTES) {
        return { status: 'too_large', bytes: value.length }
    }
    return {
        status: 'encoded',
        message: {
            key: job.id,
            value,
            headers: {
                intake_version: String(INTAKE_MESSAGE_VERSION),
                team_id: String(job.teamId),
                run_kind: kind,
                run_id: job.id,
            },
        },
    }
}

export function decodeIntakeMessage(value: Buffer | null | undefined): DecodeResult {
    let json: unknown
    try {
        json = parseJSON(value?.toString('utf-8') ?? '')
    } catch {
        return { status: 'dead_letter', reason: 'not_json' }
    }
    const parsed = IntakeMessageSchema.safeParse(json)
    return parsed.success
        ? { status: 'decoded', message: parsed.data }
        : { status: 'dead_letter', reason: 'schema_invalid' }
}

export function intakeJobInit({ teamId, job }: IntakeMessage): CyclotronV2JobInit & { id: string } {
    return {
        id: job.id,
        teamId,
        functionId: job.functionId,
        queueName: job.queueName,
        priority: job.priority,
        scheduled: new Date(job.scheduled),
        parentRunId: job.parentRunId,
        state: job.state ? Buffer.from(JSON.stringify(job.state)) : null,
        distinctId: job.distinctId,
        personId: job.personId,
        actionId: job.actionId,
    }
}
