import { randomUUID } from 'crypto'

import { parseJSON } from '~/common/utils/json-parse'

import { durationMs } from '../duration'
import { Controller } from './admission'
import { Aws, AwsError } from './aws'
import { Manifest, evidenceOf, keyOf, manifestOf, release, unreleasedRuns } from './lease'
import { CloudProfile } from './profile'
import { POLL_MS, RUN_TAG, settledStatus, stackStatus } from './stack'

type Resource = { type: string; id: string }

export type Receipt = {
    runId: string
    stackName: string
    checkedAt: string
    clean: boolean
    unlisted: string[]
    resources: (Resource & { state: string })[]
    clusterGoneListedBy?: string
}

const GONE = 'gone'
const DELETE_ATTEMPTS = 2
const TAG_LISTING_LAG_MS = 15 * 60_000
const CLUSTER = 'AWS::RDS::DBCluster'
const RDS_CLUSTER_TAG = 'aws:rds:primaryDBClusterArn'
const STACK = 'AWS::CloudFormation::Stack'
const UNKNOWN = 'unknown'

const ARN_TYPES: [RegExp, string][] = [
    [/^arn:aws:cloudformation:[^:]*:[^:]*:stack\/([^/]+)\/.+$/, STACK],
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
    return { type: UNKNOWN, id: arn }
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

async function stateOf(controller: Controller, { type, id }: Resource): Promise<string> {
    const { aws } = controller
    switch (type) {
        case STACK:
            return (await stackStatus(controller, id)) ?? GONE
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

type Inventory = Map<string, Resource>

const keyOfResource = ({ type, id }: Resource): string => `${type} ${id}`

async function listInto(
    inventory: Inventory,
    failures: string[],
    source: string,
    list: () => Promise<Resource[]>
): Promise<Resource[]> {
    try {
        const found = await list()
        found.forEach((resource) => inventory.set(keyOfResource(resource), resource))
        return found
    } catch (error) {
        failures.push(`${source} (${(error as Error).message})`)
        return []
    }
}

async function discover(
    { aws }: Controller,
    { region, account }: CloudProfile,
    manifest: Manifest,
    inventory: Inventory
): Promise<{ failures: string[]; tagged: Set<string>; blind: boolean }> {
    const failures: string[] = []
    const list = (source: string, read: () => Promise<Resource[]>): Promise<Resource[]> =>
        listInto(inventory, failures, source, read)
    await list(`the resources of stack ${manifest.stackName}`, async () => {
        const listed = await orGone(
            aws.call(['cloudformation', 'describe-stack-resources', '--stack-name', manifest.stackName]),
            ({ StackResources }) => StackResources as { ResourceType: string; PhysicalResourceId?: string }[],
            'ValidationError'
        )
        return listed === GONE
            ? []
            : listed
                  .filter(({ PhysicalResourceId }) => PhysicalResourceId)
                  .map(({ ResourceType, PhysicalResourceId }) => ({ type: ResourceType, id: PhysicalResourceId! }))
    })
    const tagged = await list(`the resources tagged ${RUN_TAG}=${manifest.runId}`, async () => {
        const { ResourceTagMappingList } = (await aws.call([
            'resourcegroupstaggingapi',
            'get-resources',
            '--tag-filters',
            `Key=${RUN_TAG},Values=${manifest.runId}`,
        ])) as { ResourceTagMappingList: { ResourceARN: string }[] }
        return ResourceTagMappingList.map(({ ResourceARN }) => resourceOfArn(ResourceARN))
    })
    let blind = false
    for (const { id } of [...inventory.values()].filter(({ type }) => type === CLUSTER)) {
        await list(`the secret and backups of cluster ${id}`, async () => {
            const copies = await liveClusterCopiesOf(aws, id)
            blind ||= copies === GONE
            return copies === GONE ? [] : copies
        })
        await list(`the secrets tagged for cluster ${id}`, () =>
            taggedSecretsOf(aws, `arn:aws:rds:${region}:${account}:cluster:${id}`)
        )
        await list(`the retained backups of cluster ${id}`, () => retainedBackupsOf(aws, id))
        await list(`the snapshots of cluster ${id}`, () => snapshotsOf(aws, id))
    }
    return { failures, tagged: new Set(tagged.map(keyOfResource)), blind }
}

async function receiptsOf(evidence: ReturnType<typeof evidenceOf>, manifest: Manifest): Promise<Receipt[]> {
    const receipts: Receipt[] = []
    for (const key of (await evidence.keys(keyOf(manifest.runId, 'receipts/'))).sort()) {
        receipts.push(parseJSON(await evidence.get(key)) as Receipt)
    }
    return receipts
}

const SECRET = 'AWS::SecretsManager::Secret'
const BACKUP = 'AWS::RDS::DBClusterAutomatedBackup'

async function liveClusterCopiesOf(aws: Aws, clusterId: string): Promise<Resource[] | typeof GONE> {
    const cluster = await orGone(
        aws.call(['rds', 'describe-db-clusters', '--db-cluster-identifier', clusterId]),
        ({ DBClusters }) => DBClusters[0] as { MasterUserSecret?: { SecretArn?: string }; DbClusterResourceId: string },
        'DBClusterNotFoundFault'
    )
    if (cluster === GONE) {
        return GONE
    }
    const { MasterUserSecret, DbClusterResourceId } = cluster
    return [
        ...(MasterUserSecret?.SecretArn ? [{ type: SECRET, id: MasterUserSecret.SecretArn }] : []),
        { type: BACKUP, id: DbClusterResourceId },
    ]
}

async function taggedSecretsOf(aws: Aws, clusterArn: string): Promise<Resource[]> {
    const { SecretList } = (await aws.call([
        'secretsmanager',
        'list-secrets',
        '--filters',
        `Key=tag-key,Values=${RDS_CLUSTER_TAG}`,
        `Key=tag-value,Values=${clusterArn}`,
    ])) as { SecretList: { ARN: string }[] }
    return SecretList.map(({ ARN }) => ({ type: SECRET, id: ARN }))
}

async function retainedBackupsOf(aws: Aws, clusterId: string): Promise<Resource[]> {
    const { DBClusterAutomatedBackups } = (await aws.call([
        'rds',
        'describe-db-cluster-automated-backups',
        '--filters',
        `Name=db-cluster-id,Values=${clusterId}`,
    ])) as { DBClusterAutomatedBackups: { DbClusterResourceId: string }[] }
    return DBClusterAutomatedBackups.map(({ DbClusterResourceId }) => ({ type: BACKUP, id: DbClusterResourceId }))
}

async function snapshotsOf(aws: Aws, clusterId: string): Promise<Resource[]> {
    const { DBClusterSnapshots } = (await aws.call([
        'rds',
        'describe-db-cluster-snapshots',
        '--db-cluster-identifier',
        clusterId,
    ])) as { DBClusterSnapshots: { DBClusterSnapshotIdentifier: string }[] }
    return DBClusterSnapshots.map(({ DBClusterSnapshotIdentifier }) => ({
        type: 'AWS::RDS::DBClusterSnapshot',
        id: DBClusterSnapshotIdentifier,
    }))
}

async function deleteStack(controller: Controller, profile: CloudProfile, manifest: Manifest, until: number) {
    let failed = 0
    for (;;) {
        try {
            await controller.aws.call([
                'cloudformation',
                'delete-stack',
                '--stack-name',
                manifest.stackName,
                '--role-arn',
                profile.baseline.stackServiceRole,
            ])
            if ((await settledStatus(controller, manifest.stackName, until)) !== 'DELETE_FAILED') {
                return
            }
            if (++failed === DELETE_ATTEMPTS) {
                return
            }
        } catch (error) {
            if (controller.now().getTime() >= until) {
                throw error
            }
            await controller.sleep(POLL_MS)
        }
    }
}

async function receiptOf(
    controller: Controller,
    profile: CloudProfile,
    manifest: Manifest,
    inventory: Inventory,
    lost: string[],
    { until, listedBy }: { until: number; listedBy: number }
): Promise<Receipt> {
    for (;;) {
        const { failures, tagged } = await discover(controller, profile, manifest, inventory)
        const resources: Receipt['resources'] = []
        for (const resource of inventory.values()) {
            const state =
                resource.type === UNKNOWN
                    ? tagged.has(keyOfResource(resource))
                        ? 'still tagged, of a type teardown does not judge'
                        : GONE
                    : await stateOf(controller, resource).catch((error: Error) => `unreadable (${error.message})`)
            resources.push({ ...resource, state })
        }
        const gone = resources.every(({ state }) => state === GONE)
        const caughtUp = controller.now().getTime() >= listedBy
        if ((gone && failures.length === 0 && caughtUp) || controller.now().getTime() >= until) {
            const unlisted = [
                ...lost,
                ...failures,
                ...(caughtUp
                    ? []
                    : [
                          `everything an earlier receipt missed, until the tag listings catch up at ${new Date(listedBy).toISOString()}`,
                      ]),
            ]
            return {
                runId: manifest.runId,
                stackName: manifest.stackName,
                checkedAt: controller.now().toISOString(),
                clean: gone && unlisted.length === 0,
                unlisted,
                resources,
            }
        }
        await controller.sleep(POLL_MS)
    }
}

const finishOf = (manifest: Manifest): string =>
    `Finish with: pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts cleanup <cloud profile> ${manifest.runId}`

export async function teardown(controller: Controller, profile: CloudProfile, manifest: Manifest): Promise<boolean> {
    let receipt: Receipt
    try {
        const until = controller.now().getTime() + durationMs(profile.admission.teardownAllowance)
        const evidence = evidenceOf(controller.aws, profile.baseline.evidenceBucket)
        const inventory: Inventory = new Map(
            [
                { type: STACK, id: manifest.stackName },
                { type: CLUSTER, id: `scn-${manifest.runId}` },
            ].map((resource) => [keyOfResource(resource), resource])
        )
        const lost: string[] = []
        let listedBy = 0
        let clusterGoneListedBy: number | undefined
        await listInto(inventory, lost, 'the earlier receipts', async () => {
            const receipts = await receiptsOf(evidence, manifest)
            if (receipts.some(({ unlisted }) => unlisted.length > 0)) {
                listedBy = Date.parse(receipts[0].checkedAt) + TAG_LISTING_LAG_MS
            }
            const stored = receipts.find((receipt) => receipt.clusterGoneListedBy)?.clusterGoneListedBy
            clusterGoneListedBy = stored === undefined ? undefined : Date.parse(stored)
            return receipts.flatMap(({ resources }) => resources.map(({ type, id }) => ({ type, id })))
        })
        const { failures, blind } = await discover(controller, profile, manifest, inventory)
        lost.push(...failures)
        await deleteStack(controller, profile, manifest, until).catch((error: Error) =>
            controller.warn(`Could not delete stack ${manifest.stackName}: ${error.message}`)
        )
        const requested = await orGone(evidence.get(keyOf(manifest.runId, 'stack-requested')), () => true, 'NoSuchKey')
        const waitsForListings = blind && requested !== GONE
        if (waitsForListings) {
            listedBy = Math.max(listedBy, clusterGoneListedBy ?? controller.now().getTime() + TAG_LISTING_LAG_MS)
        }
        receipt = await receiptOf(controller, profile, manifest, inventory, lost, { until, listedBy })
        const stackGone = receipt.resources.some(({ type, state }) => type === STACK && state === GONE)
        const graceEnd =
            clusterGoneListedBy ??
            (waitsForListings && stackGone ? Date.parse(receipt.checkedAt) + TAG_LISTING_LAG_MS : undefined)
        if (graceEnd !== undefined) {
            receipt = { ...receipt, clusterGoneListedBy: new Date(graceEnd).toISOString() }
        }
        await evidence.put(
            keyOf(manifest.runId, `receipts/${receipt.checkedAt}-${randomUUID()}.json`),
            JSON.stringify(receipt, null, 2)
        )
    } catch (error) {
        controller.warn(
            [
                `Could not finish tearing down run ${manifest.runId}, so its stack-delete schedules stay: ${(error as Error).message}`,
                finishOf(manifest),
            ].join('\n')
        )
        return false
    }
    if (!receipt.clean) {
        controller.warn(
            [
                `Run ${manifest.runId} left these behind, so its stack-delete schedules stay:`,
                ...receipt.resources
                    .filter(({ state }) => state !== GONE)
                    .map(({ type, id, state }) => `- ${type} ${id}: ${state}`),
                ...receipt.unlisted.map((source) => `- could not list ${source}`),
                finishOf(manifest),
            ].join('\n')
        )
        return false
    }
    try {
        await release(controller, profile.baseline.evidenceBucket, manifest)
        return true
    } catch (error) {
        controller.warn(
            [
                `Run ${manifest.runId} left nothing behind, but releasing its lease failed: ${(error as Error).message}`,
                finishOf(manifest),
            ].join('\n')
        )
        return false
    }
}

export async function teardownExpired(
    controller: Controller,
    profile: CloudProfile,
    { retryLeftovers }: { retryLeftovers: boolean }
): Promise<boolean> {
    const bucket = profile.baseline.evidenceBucket
    const evidence = evidenceOf(controller.aws, bucket)
    let clean = true
    for (const runId of await unreleasedRuns(controller, bucket)) {
        try {
            const manifest = await manifestOf(controller, bucket, runId)
            if (Date.parse(manifest.expiresAt) > controller.now().getTime()) {
                continue
            }
            const latest = (await receiptsOf(evidence, manifest)).at(-1)
            if (!retryLeftovers && latest && !latest.clean) {
                controller.warn(`Expired run ${runId} left resources behind.\n${finishOf(manifest)}`)
                clean = false
            } else {
                clean = (await teardown(controller, profile, manifest)) && clean
            }
        } catch (error) {
            controller.warn(`Could not tear down expired run ${runId}: ${(error as Error).message}`)
            clean = false
        }
    }
    return clean
}
