import { randomUUID } from 'crypto'
import { mkdtempDisposableSync, readFileSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

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
}

const HOUR_MS = 60 * 60 * 1000
const DELETE_STACK = 'arn:aws:scheduler:::aws-sdk:cloudformation:deleteStack'

export class LeaseError extends Error {}

const keyOf = (runId: string, name: string): string => `runs/${runId}/${name}`

const scratchDir = (): ReturnType<typeof mkdtempDisposableSync> =>
    mkdtempDisposableSync(path.join(os.tmpdir(), 'scenario-cloud-'))

function bucketOf(aws: Aws, bucket: string) {
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
        delete: (key: string): Promise<unknown> =>
            aws.call(['s3api', 'delete-object', '--bucket', bucket, '--key', key]),
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
    for (const { name, expression } of schedules) {
        const read = (await controller.aws.call(['scheduler', 'get-schedule', '--name', name])) as {
            ScheduleExpression: string
            Target: { Input: string }
        }
        if (read.ScheduleExpression !== expression || read.Target.Input !== target.Input) {
            throw new LeaseError(`Schedule ${name} reads back as ${read.ScheduleExpression} for ${read.Target.Input}.`)
        }
    }
}

export async function lease(
    controller: Controller,
    { profile, inputs }: RunInputs,
    { owner, commit }: Admitted
): Promise<Manifest> {
    const runId = randomUUID()
    const createdAt = controller.now()
    const stackName = `scn-${runId}`
    const manifest: Manifest = {
        runId,
        owner,
        account: profile.account,
        region: profile.region,
        commit,
        createdAt: createdAt.toISOString(),
        expiresAt: new Date(createdAt.getTime() + TTL_HOURS * HOUR_MS).toISOString(),
        stackName,
        schedules: [`${stackName}-expiry`, `${stackName}-expiry-retry`],
        inputs: Object.fromEntries(inputs.map(({ file, sha256 }) => [file, sha256])),
    }
    const bucket = bucketOf(controller.aws, profile.baseline.evidenceBucket)
    try {
        const body = JSON.stringify(manifest, null, 2)
        await bucket.put(keyOf(runId, 'manifest.json'), body)
        await bucket.put(keyOf(runId, 'input/manifest.json'), body)
        for (const input of inputs) {
            await bucket.put(keyOf(runId, `input/${input.file}`), input.bytes)
        }
        await register(controller, profile.baseline.schedulerRole, manifest)
        return manifest
    } catch (error) {
        const reason = (error as Error).message
        const remaining = await removePartialLease(controller, bucket, manifest)
        if (remaining.length > 0) {
            throw new LeaseError(
                `Could not lease run ${runId}: ${reason}\nRemove what remains by hand:\n${remaining.map((item) => `- ${item}`).join('\n')}`
            )
        }
        throw new LeaseError(`Could not lease run ${runId}, so nothing was created: ${reason}`)
    }
}

async function removePartialLease(
    { aws }: Controller,
    bucket: ReturnType<typeof bucketOf>,
    manifest: Manifest
): Promise<string[]> {
    const remaining: string[] = []
    const attempt = async (item: string, removal: () => Promise<unknown>): Promise<void> => {
        await removal().catch(() => remaining.push(item))
    }
    for (const name of manifest.schedules) {
        await attempt(`schedule ${name}`, () =>
            ignoringNotFound(aws.call(['scheduler', 'delete-schedule', '--name', name]))
        )
    }
    const prefix = keyOf(manifest.runId, '')
    const keys = await bucket.keys(prefix).catch(() => {
        remaining.push(`s3://${bucket.name}/${prefix}`)
        return []
    })
    for (const key of keys) {
        await attempt(`s3://${bucket.name}/${key}`, () => bucket.delete(key))
    }
    return remaining
}

export async function release(controller: Controller, evidenceBucket: string, manifest: Manifest): Promise<void> {
    await deleteSchedules(controller, manifest)
    await bucketOf(controller.aws, evidenceBucket).put(
        keyOf(manifest.runId, 'teardown.json'),
        JSON.stringify({ releasedAt: controller.now().toISOString() })
    )
    controller.print(`Released run ${manifest.runId}.`)
}

export async function manifestOf(controller: Controller, evidenceBucket: string, runId: string): Promise<Manifest> {
    try {
        return parseJSON(await bucketOf(controller.aws, evidenceBucket).get(keyOf(runId, 'manifest.json'))) as Manifest
    } catch (error) {
        if (error instanceof AwsError && error.code === 'NoSuchKey') {
            throw new LeaseError(`Run ${runId} has no manifest in ${evidenceBucket}.`)
        }
        throw error
    }
}

export async function sweepExpired(controller: Controller, evidenceBucket: string): Promise<void> {
    const keys = new Set(await bucketOf(controller.aws, evidenceBucket).keys('runs/'))
    const unreleased = [...keys]
        .filter((key) => key.endsWith('/manifest.json') && key.split('/').length === 3)
        .map((key) => key.split('/')[1])
        .filter((runId) => !keys.has(keyOf(runId, 'teardown.json')))
    for (const runId of unreleased) {
        const manifest = await manifestOf(controller, evidenceBucket, runId)
        if (Date.parse(manifest.expiresAt) <= controller.now().getTime()) {
            await release(controller, evidenceBucket, manifest)
        }
    }
}
