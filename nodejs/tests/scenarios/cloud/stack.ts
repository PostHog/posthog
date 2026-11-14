import path from 'path'

import { durationMs } from '../duration'
import { Controller } from './admission'
import { AwsError } from './aws'
import { Manifest, evidenceOf, keyOf } from './lease'
import { CloudProfile } from './profile'

export const RUN_TAG = 'scenario-run'
export const POLL_MS = 15_000

const TEMPLATE = path.join(__dirname, 'run-stack.yaml')
const SETTLED = /(_COMPLETE|_FAILED)$/

export async function stackStatus({ aws }: Controller, stackName: string): Promise<string | undefined> {
    try {
        const { Stacks } = (await aws.call(['cloudformation', 'describe-stacks', '--stack-name', stackName])) as {
            Stacks: { StackStatus: string }[]
        }
        return Stacks[0]?.StackStatus
    } catch (error) {
        if (error instanceof AwsError && error.code === 'ValidationError' && error.stderr.includes('does not exist')) {
            return undefined
        }
        throw error
    }
}

export async function settledStatus(
    controller: Controller,
    stackName: string,
    until: number,
    signal?: AbortSignal
): Promise<string | undefined> {
    for (;;) {
        const status = await stackStatus(controller, stackName)
        signal?.throwIfAborted()
        if (status === undefined || SETTLED.test(status) || controller.now().getTime() >= until) {
            return status
        }
        await controller.sleep(POLL_MS)
    }
}

function parametersOf(profile: CloudProfile, manifest: Manifest, image: string): Record<string, string> {
    const { baseline, host } = profile
    return {
        RunId: manifest.runId,
        Commit: manifest.commit,
        EvidenceBucket: baseline.evidenceBucket,
        ExpiresAt: manifest.expiresAt,
        EngineVersion: profile.engineVersion,
        WriterClass: profile.writerClass,
        ReaderMaxAcu: String(profile.readerAcu.max),
        ReaderEnabled: 'false',
        AvailabilityZone: profile.availabilityZone,
        DbSubnetGroup: baseline.dbSubnetGroup,
        DatabaseSecurityGroup: baseline.databaseSecurityGroup,
        ClusterParameterGroup: baseline.clusterParameterGroup,
        InstanceParameterGroup: baseline.instanceParameterGroup,
        MonitoringRole: baseline.monitoringRole,
        HostSubnet: baseline.hostSubnet,
        HostSecurityGroup: baseline.hostSecurityGroup,
        HostInstanceProfile: baseline.hostInstanceProfile,
        HostClass: host.class,
        HostEbsGb: String(host.ebsGb),
        HostImage: image,
    }
}

const parametersArg = (values: Record<string, string>): string =>
    JSON.stringify(Object.entries(values).map(([ParameterKey, ParameterValue]) => ({ ParameterKey, ParameterValue })))

async function imageOf({ aws }: Controller, profile: CloudProfile): Promise<string> {
    const { Parameter } = (await aws.call(['ssm', 'get-parameter', '--name', profile.host.imageParameter])) as {
        Parameter: { Value: string }
    }
    return Parameter.Value
}

function refuseCreationNearExpiry(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    what: string
): void {
    const lastCreation = Date.parse(manifest.expiresAt) - durationMs(profile.admission.teardownAllowance)
    if (controller.now().getTime() >= lastCreation) {
        throw new Error(`The lease ends at ${manifest.expiresAt}, too soon to ${what}.`)
    }
}

async function waitForHost(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    signal: AbortSignal
): Promise<void> {
    const evidence = evidenceOf(controller.aws, profile.baseline.evidenceBucket)
    const lastWork = Date.parse(manifest.expiresAt) - durationMs(profile.admission.teardownAllowance)
    const deadline = Math.min(controller.now().getTime() + durationMs(profile.host.bootstrapDeadline), lastWork)
    for (;;) {
        const markers = await evidence.keys(keyOf(manifest.runId, 'host/'))
        if (markers.includes(keyOf(manifest.runId, 'host/failed'))) {
            throw new Error(
                `The run host failed to bootstrap. Its log is s3://${evidence.name}/${keyOf(manifest.runId, 'host/bootstrap.log')}.`
            )
        }
        if (markers.includes(keyOf(manifest.runId, 'host/ready'))) {
            return
        }
        if (controller.now().getTime() >= deadline) {
            throw new Error(
                deadline === lastWork
                    ? `The run host was not ready by ${new Date(lastWork).toISOString()}, which leaves the lease ending at ${manifest.expiresAt} only its teardown allowance.`
                    : `The run host was not ready within ${profile.host.bootstrapDeadline}.`
            )
        }
        signal.throwIfAborted()
        await controller.sleep(POLL_MS)
    }
}

export async function createRunStack(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    signal: AbortSignal
): Promise<Record<string, string>> {
    const parameters = parametersOf(profile, manifest, await imageOf(controller, profile))
    refuseCreationNearExpiry(controller, profile, manifest, 'create the stack')
    signal.throwIfAborted()
    await evidenceOf(controller.aws, profile.baseline.evidenceBucket).put(
        keyOf(manifest.runId, 'stack-requested'),
        manifest.stackName
    )
    await controller.aws.call([
        'cloudformation',
        'create-stack',
        '--stack-name',
        manifest.stackName,
        '--template-body',
        `file://${TEMPLATE}`,
        '--parameters',
        parametersArg(parameters),
        '--role-arn',
        profile.baseline.stackServiceRole,
        '--on-failure',
        'DELETE',
        '--client-request-token',
        `create-${manifest.runId}`,
        '--tags',
        JSON.stringify([{ Key: RUN_TAG, Value: manifest.runId }]),
    ])
    const status = await settledStatus(controller, manifest.stackName, Date.parse(manifest.expiresAt), signal)
    if (status !== 'CREATE_COMPLETE') {
        throw new Error(`Stack ${manifest.stackName} ended ${status ?? 'deleted'}, not CREATE_COMPLETE.`)
    }
    await waitForHost(controller, profile, manifest, signal)
    return parameters
}

export async function addReader(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    parameters: Record<string, string>,
    signal: AbortSignal
): Promise<void> {
    refuseCreationNearExpiry(controller, profile, manifest, 'add the reader')
    signal.throwIfAborted()
    await controller.aws.call([
        'cloudformation',
        'update-stack',
        '--stack-name',
        manifest.stackName,
        '--use-previous-template',
        '--parameters',
        parametersArg({ ...parameters, ReaderEnabled: 'true' }),
        '--role-arn',
        profile.baseline.stackServiceRole,
    ])
    const status = await settledStatus(controller, manifest.stackName, Date.parse(manifest.expiresAt), signal)
    if (status !== 'UPDATE_COMPLETE') {
        throw new Error(`Stack ${manifest.stackName} ended ${status ?? 'deleted'}, not UPDATE_COMPLETE.`)
    }
}
