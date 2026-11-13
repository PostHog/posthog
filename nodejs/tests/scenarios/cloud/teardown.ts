import { durationMs } from '../duration'
import { Controller } from './admission'
import { Aws, AwsError } from './aws'
import { Manifest, evidenceOf, keyOf, manifestOf, release, unreleasedRuns } from './lease'
import { CloudProfile } from './profile'
import { POLL_MS, RUN_TAG, RunInvalid, settledStatus } from './stack'

type Resource = { type: string; id: string }

export type Receipt = {
    runId: string
    stackName: string
    checkedAt: string
    clean: boolean
    resources: (Resource & { state: string })[]
}

const GONE = 'gone'
const DELETE_ATTEMPTS = 2
const CLUSTER = 'AWS::RDS::DBCluster'

const ARN_TYPES: [RegExp, string][] = [
    [/^arn:aws:rds:[^:]*:[^:]*:cluster:(.+)$/, CLUSTER],
    [/^arn:aws:rds:[^:]*:[^:]*:db:(.+)$/, 'AWS::RDS::DBInstance'],
    [/^arn:aws:rds:[^:]*:[^:]*:cluster-snapshot:(.+)$/, 'AWS::RDS::DBClusterSnapshot'],
    [/^arn:aws:ec2:[^:]*:[^:]*:instance\/(.+)$/, 'AWS::EC2::Instance'],
    [/^arn:aws:ec2:[^:]*:[^:]*:volume\/(.+)$/, 'AWS::EC2::Volume'],
    [/^(arn:aws:secretsmanager:.+)$/, 'AWS::SecretsManager::Secret'],
]

function resourceOfArn(arn: string): Resource {
    for (const [pattern, type] of ARN_TYPES) {
        const match = pattern.exec(arn)
        if (match) {
            return { type, id: match[1] }
        }
    }
    return { type: 'unknown', id: arn }
}

const notFound = (error: unknown, ...codes: string[]): boolean =>
    error instanceof AwsError && codes.includes(error.code ?? '')

async function orGone<T>(
    request: Promise<unknown>,
    read: (answer: any) => T,
    ...codes: string[]
): Promise<T | typeof GONE> {
    try {
        return read(await request)
    } catch (error) {
        if (notFound(error, ...codes)) {
            return GONE
        }
        throw error
    }
}

function stateOf(aws: Aws, { type, id }: Resource): Promise<string> {
    switch (type) {
        case CLUSTER:
            return orGone(
                aws.call(['rds', 'describe-db-clusters', '--db-cluster-identifier', id]),
                ({ DBClusters }) => DBClusters[0].Status,
                'DBClusterNotFoundFault'
            )
        case 'AWS::RDS::DBInstance':
            return orGone(
                aws.call(['rds', 'describe-db-instances', '--db-instance-identifier', id]),
                ({ DBInstances }) => DBInstances[0].DBInstanceStatus,
                'DBInstanceNotFound'
            )
        case 'AWS::RDS::DBClusterSnapshot':
            return orGone(
                aws.call(['rds', 'describe-db-cluster-snapshots', '--db-cluster-snapshot-identifier', id]),
                ({ DBClusterSnapshots }) => DBClusterSnapshots[0].Status,
                'DBClusterSnapshotNotFoundFault'
            )
        case 'AWS::RDS::DBClusterAutomatedBackup':
            return orGone(
                aws.call(['rds', 'describe-db-cluster-automated-backups', '--db-cluster-resource-id', id]),
                ({ DBClusterAutomatedBackups }) => DBClusterAutomatedBackups[0]?.Status ?? GONE,
                'DBClusterAutomatedBackupNotFoundFault'
            )
        case 'AWS::EC2::Instance':
            return orGone(
                aws.call(['ec2', 'describe-instances', '--instance-ids', id]),
                ({ Reservations }) => {
                    const state = Reservations[0]?.Instances[0]?.State.Name ?? GONE
                    return state === 'terminated' ? GONE : state
                },
                'InvalidInstanceID.NotFound'
            )
        case 'AWS::EC2::Volume':
            return orGone(
                aws.call(['ec2', 'describe-volumes', '--volume-ids', id]),
                ({ Volumes }) => Volumes[0]?.State ?? GONE,
                'InvalidVolume.NotFound'
            )
        case 'AWS::SecretsManager::Secret':
            return orGone(
                aws.call(['secretsmanager', 'describe-secret', '--secret-id', id]),
                ({ DeletedDate }) => (DeletedDate ? GONE : 'active'),
                'ResourceNotFoundException'
            )
        default:
            return Promise.resolve(`not judged (${type})`)
    }
}

async function inventoryOf({ aws }: Controller, manifest: Manifest): Promise<Resource[]> {
    const found = new Map<string, Resource>()
    const add = (resource: Resource): void => {
        found.set(`${resource.type} ${resource.id}`, resource)
    }
    try {
        const { StackResources } = (await aws.call([
            'cloudformation',
            'describe-stack-resources',
            '--stack-name',
            manifest.stackName,
        ])) as { StackResources: { ResourceType: string; PhysicalResourceId?: string }[] }
        StackResources.filter(({ PhysicalResourceId }) => PhysicalResourceId).forEach(
            ({ ResourceType, PhysicalResourceId }) => add({ type: ResourceType, id: PhysicalResourceId! })
        )
    } catch (error) {
        if (!(error instanceof AwsError && error.code === 'ValidationError')) {
            throw error
        }
    }
    const { ResourceTagMappingList } = (await aws.call([
        'resourcegroupstaggingapi',
        'get-resources',
        '--tag-filters',
        `Key=${RUN_TAG},Values=${manifest.runId}`,
    ])) as { ResourceTagMappingList: { ResourceARN: string }[] }
    ResourceTagMappingList.forEach(({ ResourceARN }) => add(resourceOfArn(ResourceARN)))
    for (const cluster of [...found.values()].filter(({ type }) => type === CLUSTER)) {
        for (const resource of await clusterCopiesOf(aws, cluster.id)) {
            add(resource)
        }
    }
    return [...found.values()]
}

async function clusterCopiesOf(aws: Aws, clusterId: string): Promise<Resource[]> {
    const copies: Resource[] = []
    const cluster = await orGone(
        aws.call(['rds', 'describe-db-clusters', '--db-cluster-identifier', clusterId]),
        ({ DBClusters }) => DBClusters[0] as { MasterUserSecret?: { SecretArn?: string }; DbClusterResourceId: string },
        'DBClusterNotFoundFault'
    )
    if (cluster !== GONE) {
        const { MasterUserSecret, DbClusterResourceId } = cluster
        if (MasterUserSecret?.SecretArn) {
            copies.push({ type: 'AWS::SecretsManager::Secret', id: MasterUserSecret.SecretArn })
        }
        copies.push({ type: 'AWS::RDS::DBClusterAutomatedBackup', id: DbClusterResourceId })
    }
    const { DBClusterSnapshots } = (await aws.call([
        'rds',
        'describe-db-cluster-snapshots',
        '--db-cluster-identifier',
        clusterId,
    ])) as { DBClusterSnapshots: { DBClusterSnapshotIdentifier: string }[] }
    DBClusterSnapshots.forEach(({ DBClusterSnapshotIdentifier }) =>
        copies.push({ type: 'AWS::RDS::DBClusterSnapshot', id: DBClusterSnapshotIdentifier })
    )
    return copies
}

async function deleteStack(controller: Controller, profile: CloudProfile, manifest: Manifest, until: number) {
    for (let attempt = 0; attempt < DELETE_ATTEMPTS; attempt++) {
        await controller.aws.call([
            'cloudformation',
            'delete-stack',
            '--stack-name',
            manifest.stackName,
            '--role-arn',
            profile.baseline.stackServiceRole,
        ])
        const status = await settledStatus(controller, manifest.stackName, until).catch((error) => {
            if (error instanceof RunInvalid) {
                return 'unsettled'
            }
            throw error
        })
        if (status !== 'DELETE_FAILED') {
            return
        }
    }
}

async function receiptOf(controller: Controller, manifest: Manifest, inventory: Resource[], until: number) {
    for (;;) {
        const resources: Receipt['resources'] = []
        for (const resource of inventory) {
            const state = await stateOf(controller.aws, resource).catch(
                (error: Error) => `unreadable (${error.message})`
            )
            resources.push({ ...resource, state })
        }
        const clean = resources.every(({ state }) => state === GONE)
        if (clean || controller.now().getTime() >= until) {
            return {
                runId: manifest.runId,
                stackName: manifest.stackName,
                checkedAt: controller.now().toISOString(),
                clean,
                resources,
            }
        }
        await controller.sleep(POLL_MS)
    }
}

export async function teardown(controller: Controller, profile: CloudProfile, manifest: Manifest): Promise<boolean> {
    const finish = `Finish with: pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts cleanup <cloud profile> ${manifest.runId}`
    try {
        const until = controller.now().getTime() + durationMs(profile.admission.teardownAllowance)
        const inventory = await inventoryOf(controller, manifest)
        await deleteStack(controller, profile, manifest, until).catch((error: Error) =>
            controller.warn(`Could not delete stack ${manifest.stackName}: ${error.message}`)
        )
        const receipt = await receiptOf(controller, manifest, inventory, until)
        const evidence = evidenceOf(controller.aws, profile.baseline.evidenceBucket)
        await evidence.put(keyOf(manifest.runId, 'receipt.json'), JSON.stringify(receipt, null, 2))
        if (receipt.clean) {
            await release(controller, profile.baseline.evidenceBucket, manifest)
            return true
        }
        const left = receipt.resources.filter(({ state }) => state !== GONE)
        controller.warn(
            [
                `Run ${manifest.runId} left these behind, so its stack-delete schedules stay:`,
                ...left.map(({ type, id, state }) => `- ${type} ${id}: ${state}`),
                finish,
            ].join('\n')
        )
    } catch (error) {
        controller.warn(
            [
                `Could not finish tearing down run ${manifest.runId}, so its stack-delete schedules stay: ${(error as Error).message}`,
                finish,
            ].join('\n')
        )
    }
    return false
}

export async function teardownExpired(controller: Controller, profile: CloudProfile): Promise<boolean> {
    const bucket = profile.baseline.evidenceBucket
    let clean = true
    for (const runId of await unreleasedRuns(controller, bucket)) {
        try {
            const manifest = await manifestOf(controller, bucket, runId)
            if (Date.parse(manifest.expiresAt) <= controller.now().getTime()) {
                clean = (await teardown(controller, profile, manifest)) && clean
            }
        } catch (error) {
            controller.warn(`Could not tear down expired run ${runId}: ${(error as Error).message}`)
            clean = false
        }
    }
    return clean
}
