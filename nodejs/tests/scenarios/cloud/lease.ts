import { randomUUID } from 'crypto'
import { mkdtempDisposableSync, readFileSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'

import { Admitted, Controller } from './admission'
import { Aws, AwsError } from './aws'
import { RunInputs, TTL_HOURS } from './profile'

export type Manifest = {
    runId: string
    owner: string
    account: string
    region: string
    commit: string
    createdAt: string
    expiresAt: string
    stackName: string
    schedules: string[]
    inputs: Record<string, string>
    card: string
    readerIdleMaxAcu?: number
}

const HOUR_MS = 60 * 60 * 1000
const DELETE_STACK = 'arn:aws:scheduler:::aws-sdk:cloudformation:deleteStack'

export class LeaseError extends Error {}

const StoredManifest = z
    .object({ runId: z.uuid(), stackName: z.string(), schedules: z.array(z.string()), expiresAt: z.iso.datetime() })
    .loose()

const stackNameOf = (runId: string): string => `scn-${runId}`

const schedulesOf = (runId: string): string[] => [`${stackNameOf(runId)}-expiry`, `${stackNameOf(runId)}-expiry-retry`]

export const keyOf = (runId: string, name: string): string => `runs/${runId}/${name}`

const scratchDir = (): ReturnType<typeof mkdtempDisposableSync> =>
    mkdtempDisposableSync(path.join(os.tmpdir(), 'scenario-cloud-'))

export function evidenceOf(aws: Aws, bucket: string) {
    return {
        name: bucket,
        put: async (key: string, body: string | Buffer): Promise<unknown> => {
            using scratch = scratchDir()
            const file = path.join(scratch.path, 'object')
            writeFileSync(file, body)
            return await aws.call(['s3api', 'put-object', '--bucket', bucket, '--key', key, '--body', file])
        },
        get: async (key: string): Promise<string> => {
            using scratch = scratchDir()
            const file = path.join(scratch.path, 'object')
            await aws.call(['s3api', 'get-object', '--bucket', bucket, '--key', key, file])
            return readFileSync(file, 'utf8')
        },
        keys: async (prefix: string): Promise<string[]> => {
            const listed = (await aws.call(['s3api', 'list-objects-v2', '--bucket', bucket, '--prefix', prefix])) as {
                Contents?: { Key: string }[]
            } | null
            return (listed?.Contents ?? []).map(({ Key }) => Key)
        },
    }
}

const expressionOf = (at: Date): string => `at(${at.toISOString().slice(0, 19)})`

const inputOf = (stackName: string): string => JSON.stringify({ StackName: stackName })

async function ignoringNotFound(request: Promise<unknown>): Promise<void> {
    try {
        await request
    } catch (error) {
        if (!(error instanceof AwsError && error.code === 'ResourceNotFoundException')) {
            throw error
        }
    }
}

async function deleteSchedules({ aws }: Controller, manifest: Manifest): Promise<void> {
    for (const name of manifest.schedules) {
        await ignoringNotFound(aws.call(['scheduler', 'delete-schedule', '--name', name]))
    }
}

async function register(controller: Controller, schedulerRole: string, manifest: Manifest): Promise<void> {
    const expiresAt = Date.parse(manifest.expiresAt)
    const schedules = manifest.schedules.map((name, i) => ({
        name,
        expression: expressionOf(new Date(expiresAt + i * HOUR_MS)),
    }))
    const target = { Arn: DELETE_STACK, RoleArn: schedulerRole, Input: inputOf(manifest.stackName) }
    for (const { name, expression } of schedules) {
        await controller.aws.call([
            'scheduler',
            'create-schedule',
            '--name',
            name,
            '--schedule-expression',
            expression,
            '--schedule-expression-timezone',
            'UTC',
            '--flexible-time-window',
            'Mode=OFF',
            '--action-after-completion',
            'DELETE',
            '--target',
            JSON.stringify(target),
        ])
    }
}

export async function lease(
    controller: Controller,
    { profile, inputs, card }: RunInputs,
    { owner, commit }: Admitted
): Promise<Manifest> {
    const runId = randomUUID()
    const createdAt = controller.now()
    const stackName = stackNameOf(runId)
    const manifest: Manifest = {
        runId,
        owner,
        account: profile.account,
        region: profile.region,
        commit,
        createdAt: createdAt.toISOString(),
        expiresAt: new Date(createdAt.getTime() + TTL_HOURS * HOUR_MS).toISOString(),
        stackName,
        schedules: schedulesOf(runId),
        inputs: Object.fromEntries(inputs.map(({ file, sha256 }) => [file, sha256])),
        card: card.id,
        readerIdleMaxAcu: profile.readerAcu.idleMax,
    }
    const bucket = evidenceOf(controller.aws, profile.baseline.evidenceBucket)
    const body = JSON.stringify(manifest, null, 2)
    try {
        await bucket.put(keyOf(runId, 'manifest.json'), body)
        await bucket.put(keyOf(runId, 'input/manifest.json'), body)
        for (const input of inputs) {
            await bucket.put(keyOf(runId, `input/${input.file}`), input.bytes)
        }
        await register(controller, profile.baseline.schedulerRole, manifest)
        return manifest
    } catch (error) {
        const left = await deleteSchedules(controller, manifest).then(
            () => [],
            (deleteError: Error) => [`its schedules ${manifest.schedules.join(', ')}: ${deleteError.message}`]
        )
        controller.warn(
            [
                `Run ${runId} was not leased: ${(error as Error).message}`,
                `Left behind: its uploads under s3://${bucket.name}/${keyOf(runId, '')}`,
                ...left,
            ].join('\n')
        )
        throw error
    }
}

export async function release(controller: Controller, manifest: Manifest): Promise<void> {
    await deleteSchedules(controller, manifest)
    controller.print(`Released run ${manifest.runId}.`)
}

export async function manifestOf(controller: Controller, evidenceBucket: string, runId: string): Promise<Manifest> {
    let stored: unknown
    try {
        stored = parseJSON(await evidenceOf(controller.aws, evidenceBucket).get(keyOf(runId, 'manifest.json')))
    } catch (error) {
        if (error instanceof AwsError && error.code === 'NoSuchKey') {
            throw new LeaseError(`Run ${runId} has no manifest in ${evidenceBucket}.`)
        }
        throw new LeaseError(`The manifest of run ${runId} cannot be read: ${(error as Error).message}`)
    }
    const parsed = StoredManifest.safeParse(stored)
    if (
        !parsed.success ||
        parsed.data.runId !== runId ||
        parsed.data.stackName !== stackNameOf(runId) ||
        parsed.data.schedules.join('\n') !== schedulesOf(runId).join('\n')
    ) {
        throw new LeaseError(
            `The manifest of run ${runId} does not name that run's stack and schedules, so it is not used.`
        )
    }
    return parsed.data as unknown as Manifest
}

const HostManifest = StoredManifest.extend({ account: z.string(), readerIdleMaxAcu: z.number().positive().optional() })

export type RunManifest = Pick<Manifest, 'runId' | 'account' | 'expiresAt' | 'stackName' | 'readerIdleMaxAcu'>

export function runManifestOf(env: NodeJS.ProcessEnv): RunManifest | undefined {
    const file = env.SCENARIO_RUN_MANIFEST
    if (!file) {
        return undefined
    }
    const parsed = HostManifest.safeParse(parseJSON(readFileSync(file, 'utf8')))
    if (!parsed.success || parsed.data.stackName !== stackNameOf(parsed.data.runId)) {
        throw new LeaseError(`The run manifest at ${file} does not name a run and its stack, so it is not used.`)
    }
    return parsed.data
}
