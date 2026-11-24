import { durationMs } from '../duration'
import { Aws } from './aws'
import { CAP_USD, CloudProfile, TTL_HOURS } from './profile'

export type Origin = {
    head(): string
    onMaster(commit: string): Promise<boolean>
    cardAt(commit: string, id: string): string
}

export type Controller = {
    aws: Aws
    origin: Origin
    now(): Date
    sleep(ms: number): Promise<void>
    onInterrupt(handler: () => void): () => void
    env: NodeJS.ProcessEnv
    print(line: string): void
    warn(line: string): void
}

export type Admitted = { owner: string; commit: string }

type EstimateLine = { item: string; usd: number }

const HOUR_S = 3600
export const HOURS_PER_MONTH = 730
const BYTES_PER_GB = 1e9
const WRITER_MONITORING_INTERVAL_SECONDS = 1
const CONTROLLER_ROLE = 'scenario-run-controller'

export function estimateOf({
    writerClass,
    readerAcu,
    readerMonitoringIntervalSeconds,
    host,
    baseline,
    admission,
}: CloudProfile): EstimateLine[] {
    const { rates, allowances } = admission
    const months = TTL_HOURS / HOURS_PER_MONTH
    const monitoringEventsPerHour =
        HOUR_S / WRITER_MONITORING_INTERVAL_SECONDS + HOUR_S / readerMonitoringIntervalSeconds
    const logGbPerHour = (monitoringEventsPerHour * allowances.enhancedMonitoringEventBytes) / BYTES_PER_GB
    const logGb = TTL_HOURS * logGbPerHour
    const fullInventoryPerHour =
        rates.writerPerHour +
        readerAcu.max * rates.acuPerHour +
        rates.hostPerHour +
        (allowances.storageGb * rates.storagePerGbMonth + baseline.hostRootVolumeGb * rates.ebsPerGbMonth) /
            HOURS_PER_MONTH +
        logGbPerHour * rates.logsIngestPerGb
    return [
        { item: `writer ${writerClass}, ${TTL_HOURS} h`, usd: TTL_HOURS * rates.writerPerHour },
        { item: `reader at ${readerAcu.max} ACU, ${TTL_HOURS} h`, usd: TTL_HOURS * readerAcu.max * rates.acuPerHour },
        { item: `host ${host.class}, ${TTL_HOURS} h`, usd: TTL_HOURS * rates.hostPerHour },
        {
            item: `Aurora storage, ${allowances.storageGb} GB bound`,
            usd: allowances.storageGb * rates.storagePerGbMonth * months,
        },
        {
            item: `host EBS, ${baseline.hostRootVolumeGb} GB`,
            usd: baseline.hostRootVolumeGb * rates.ebsPerGbMonth * months,
        },
        { item: `Enhanced Monitoring logs, ${logGb.toFixed(2)} GB`, usd: logGb * rates.logsIngestPerGb },
        { item: `transfer, ${allowances.transferGb} GB`, usd: allowances.transferGb * rates.transferPerGb },
        {
            item: `S3 requests, ${allowances.s3Requests}`,
            usd: (allowances.s3Requests / 1000) * rates.s3PerThousandRequests,
        },
        {
            item: `teardown tail, ${admission.teardownAllowance} of the full inventory`,
            usd: (durationMs(admission.teardownAllowance) / (HOUR_S * 1000)) * fullInventoryPerHour,
        },
        { item: 'margin', usd: admission.reserve.marginUsd },
    ]
}

export const dollars = (usd: number): string => `$${usd.toFixed(2)}`

function printEstimate({ print }: Controller, profile: CloudProfile): number {
    const lines = estimateOf(profile)
    const total = lines.reduce((sum, { usd }) => sum + usd, 0)
    const { version, feeds } = profile.admission.priceList
    print(`Worst case at price list ${version} (${feeds.map(({ url, sha256 }) => `${url} ${sha256}`).join(', ')}):`)
    lines.forEach(({ item, usd }) => print(`  ${item}: ${dollars(usd)}`))
    print(`Admitted estimate: ${dollars(total)} of the $${CAP_USD} cap. It is not a bill ceiling.`)
    return total
}

export async function refuseOutsideDev({ aws }: Controller, account: string): Promise<void> {
    const { Account, Arn } = (await aws.call(['sts', 'get-caller-identity'])) as { Account: string; Arn: string }
    if (/^arn:aws:sts::\d{12}:assumed-role\/([^/]+)\//.exec(Arn)?.[1] !== CONTROLLER_ROLE) {
        throw new Error(
            `Refused: the credentials are for ${Arn}. A cloud run acts only as the ${CONTROLLER_ROLE} role, which the failover baseline creates in the dev account alone. Use a profile that assumes that role.`
        )
    }
    if (Account !== account) {
        throw new Error(`Refused: the credentials are for account ${Account}, and the profile names ${account}.`)
    }
}

export async function admit(
    controller: Controller,
    profile: CloudProfile
): Promise<{ admitted: Admitted } | { problems: string[] }> {
    const { aws, origin } = controller
    const problems: string[] = []
    const identity = (await aws.call(['sts', 'get-caller-identity'])) as { Arn: string }
    const commit = origin.head()
    if (!(await origin.onMaster(commit))) {
        problems.push(
            `Commit ${commit} is not on the master branch of PostHog/posthog, and the run host installs only merged code. Run from a merged commit.`
        )
    }
    if (printEstimate(controller, profile) > CAP_USD) {
        problems.push(`The admitted estimate is over the $${CAP_USD} cap.`)
    }
    return problems.length > 0 ? { problems } : { admitted: { owner: identity.Arn, commit } }
}
