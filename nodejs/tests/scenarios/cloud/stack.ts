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

export class RunInvalid extends Error {}

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
        if (status === undefined || SETTLED.test(status)) {
            return status
        }
        if (controller.now().getTime() >= until) {
            throw new RunInvalid(`Stack ${stackName} is still ${status}.`)
        }
        signal?.throwIfAborted()
        await controller.sleep(POLL_MS)
    }
}

function parametersOf(profile: CloudProfile, manifest: Manifest, readerEnabled: boolean): string {
    const { baseline, host } = profile
    const values: Record<string, string> = {
        RunId: manifest.runId,
        Commit: manifest.commit,
        EvidenceBucket: baseline.evidenceBucket,
        ExpiresAt: manifest.expiresAt,
        EngineVersion: profile.engineVersion,
        WriterClass: profile.writerClass,
        ReaderMaxAcu: String(profile.readerAcu.max),
        ReaderEnabled: String(readerEnabled),
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
        HostImage: host.imageParameter,
    }
    return JSON.stringify(
        Object.entries(values).map(([ParameterKey, ParameterValue]) => ({ ParameterKey, ParameterValue }))
    )
}

function refuseCreationNearExpiry(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    what: string
): void {
    const lastCreation = Date.parse(manifest.expiresAt) - durationMs(profile.admission.teardownAllowance)
    if (controller.now().getTime() >= lastCreation) {
        throw new RunInvalid(`The lease ends at ${manifest.expiresAt}, too soon to ${what}.`)
    }
}

async function waitForHost(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    signal: AbortSignal
): Promise<void> {
    const evidence = evidenceOf(controller.aws, profile.baseline.evidenceBucket)
    const deadline = controller.now().getTime() + durationMs(profile.host.bootstrapDeadline)
    for (;;) {
        const markers = await evidence.keys(keyOf(manifest.runId, 'host/'))
        if (markers.includes(keyOf(manifest.runId, 'host/failed'))) {
            throw new RunInvalid(
                `The run host failed to bootstrap. Its log is s3://${evidence.name}/${keyOf(manifest.runId, 'host/bootstrap.log')}.`
            )
        }
        if (markers.includes(keyOf(manifest.runId, 'host/ready'))) {
            return
        }
        if (controller.now().getTime() >= deadline) {
            throw new RunInvalid(`The run host was not ready within ${profile.host.bootstrapDeadline}.`)
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
): Promise<void> {
    refuseCreationNearExpiry(controller, profile, manifest, 'create the stack')
    await controller.aws.call([
        'cloudformation',
        'create-stack',
        '--stack-name',
        manifest.stackName,
        '--template-body',
        `file://${TEMPLATE}`,
        '--parameters',
        parametersOf(profile, manifest, false),
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
        throw new RunInvalid(`Stack ${manifest.stackName} ended ${status ?? 'deleted'}, not CREATE_COMPLETE.`)
    }
    await waitForHost(controller, profile, manifest, signal)
}

export async function addReader(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    signal: AbortSignal
): Promise<void> {
    refuseCreationNearExpiry(controller, profile, manifest, 'add the reader')
    await controller.aws.call([
        'cloudformation',
        'update-stack',
        '--stack-name',
        manifest.stackName,
        '--use-previous-template',
        '--parameters',
        parametersOf(profile, manifest, true),
        '--role-arn',
        profile.baseline.stackServiceRole,
    ])
    const status = await settledStatus(controller, manifest.stackName, Date.parse(manifest.expiresAt), signal)
    if (status !== 'UPDATE_COMPLETE') {
        throw new RunInvalid(`Stack ${manifest.stackName} ended ${status ?? 'deleted'}, not UPDATE_COMPLETE.`)
    }
}
