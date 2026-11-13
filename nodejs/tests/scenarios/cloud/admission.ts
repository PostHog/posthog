import { createHash } from 'crypto'
import { readFileSync } from 'fs'
import os from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { durationMs } from '../duration'
import { Aws, AwsError } from './aws'
import { CAP_USD, CloudProfile, TTL_HOURS } from './profile'

export type Origin = { head(): string; published(commit: string): Promise<boolean> }

export type Controller = {
    aws: Aws
    origin: Origin
    now(): Date
    env: NodeJS.ProcessEnv
    print(line: string): void
    warn(line: string): void
}

export type Admitted = { owner: string; commit: string }

type EstimateLine = { item: string; usd: number }

const HOUR_S = 3600
const HOURS_PER_MONTH = 730
const BYTES_PER_GB = 1e9
const MONITORED_INSTANCES = 2
const SERVERLESS_CLASS = 'db.serverless'
const DENIED = ['AccessDenied', 'AccessDeniedException', 'UnauthorizedOperation', 'UnauthorizedException']
const PROBE_ID = 'scn-permission-probe'

export function estimateOf({ writerClass, readerAcu, host, admission }: CloudProfile): EstimateLine[] {
    const { rates, allowances } = admission
    const months = TTL_HOURS / HOURS_PER_MONTH
    const logGbPerHour = (MONITORED_INSTANCES * HOUR_S * allowances.enhancedMonitoringEventBytes) / BYTES_PER_GB
    const logGb = TTL_HOURS * logGbPerHour
    const fullInventoryPerHour =
        rates.writerPerHour +
        readerAcu.max * rates.acuPerHour +
        rates.hostPerHour +
        (allowances.storageGb * rates.storagePerGbMonth + host.ebsGb * rates.ebsPerGbMonth) / HOURS_PER_MONTH +
        logGbPerHour * rates.logsIngestPerGb
    return [
        { item: `writer ${writerClass}, ${TTL_HOURS} h`, usd: TTL_HOURS * rates.writerPerHour },
        { item: `reader at ${readerAcu.max} ACU, ${TTL_HOURS} h`, usd: TTL_HOURS * readerAcu.max * rates.acuPerHour },
        { item: `host ${host.class}, ${TTL_HOURS} h`, usd: TTL_HOURS * rates.hostPerHour },
        {
            item: `Aurora storage, ${allowances.storageGb} GB bound`,
            usd: allowances.storageGb * rates.storagePerGbMonth * months,
        },
        { item: `host EBS, ${host.ebsGb} GB`, usd: host.ebsGb * rates.ebsPerGbMonth * months },
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

const dollars = (usd: number): string => `$${usd.toFixed(2)}`

function printEstimate({ print }: Controller, profile: CloudProfile): number {
    const lines = estimateOf(profile)
    const total = lines.reduce((sum, { usd }) => sum + usd, 0)
    const { version, feeds } = profile.admission.priceList
    print(`Worst case at price list ${version} (${feeds.map(({ url, sha256 }) => `${url} ${sha256}`).join(', ')}):`)
    lines.forEach(({ item, usd }) => print(`  ${item}: ${dollars(usd)}`))
    print(`Admitted estimate: ${dollars(total)} of the $${CAP_USD} cap. It is not a bill ceiling.`)
    return total
}

type Session = { endsAt: Date } | { refreshable: true } | { unknown: true } | { problem: string }

function cachedSsoToken(home: string, ssoSession: string): { expiresAt?: string; refreshToken?: string } | undefined {
    const name = `${createHash('sha1').update(ssoSession).digest('hex')}.json`
    try {
        return parseJSON(readFileSync(path.join(home, '.aws', 'sso', 'cache', name), 'utf8'))
    } catch {
        return undefined
    }
}

function endOf(expiry: string | undefined): Session {
    if (!expiry) {
        return { unknown: true }
    }
    const endsAt = new Date(expiry)
    return Number.isFinite(endsAt.getTime())
        ? { endsAt }
        : { problem: `The credentials report an unreadable expiry, ${expiry}. Sign in again.` }
}

async function sessionOf({ aws, env }: Controller): Promise<Session> {
    const ssoSession = env.AWS_ACCESS_KEY_ID ? '' : await aws.text(['configure', 'get', 'sso_session']).catch(() => '')
    if (ssoSession === '') {
        const { Expiration } = parseJSON(
            await aws.text(['configure', 'export-credentials', '--format', 'process'])
        ) as { Expiration?: string }
        return endOf(Expiration)
    }
    const token = cachedSsoToken(env.HOME ?? os.homedir(), ssoSession)
    if (token === undefined) {
        return { problem: `No SSO token is cached for ${ssoSession}. Run aws sso login --sso-session ${ssoSession}.` }
    }
    if (token.refreshToken) {
        return { refreshable: true }
    }
    return endOf(token.expiresAt)
}

function probesOf({ baseline }: CloudProfile, now: Date): [string, string[]][] {
    const minuteAgo = new Date(now.getTime() - 60_000).toISOString()
    return [
        ['cloudformation:DescribeStacks', ['cloudformation', 'describe-stacks', '--stack-name', PROBE_ID]],
        ['scheduler:GetSchedule', ['scheduler', 'get-schedule', '--name', PROBE_ID]],
        [
            's3:ListBucket',
            ['s3api', 'list-objects-v2', '--bucket', baseline.evidenceBucket, '--prefix', 'runs/', '--max-items', '1'],
        ],
        [
            'ssm:GetCommandInvocation',
            [
                'ssm',
                'get-command-invocation',
                '--command-id',
                '00000000-0000-0000-0000-000000000000',
                '--instance-id',
                'i-00000000000000000',
            ],
        ],
        [
            'cloudwatch:GetMetricData',
            [
                'cloudwatch',
                'get-metric-data',
                '--start-time',
                minuteAgo,
                '--end-time',
                now.toISOString(),
                '--metric-data-queries',
                JSON.stringify([
                    {
                        Id: 'probe',
                        MetricStat: {
                            Metric: { Namespace: 'AWS/RDS', MetricName: 'ServerlessDatabaseCapacity' },
                            Period: 60,
                            Stat: 'Maximum',
                        },
                    },
                ]),
            ],
        ],
        [
            'logs:FilterLogEvents',
            [
                'logs',
                'filter-log-events',
                '--log-group-name',
                'RDSOSMetrics',
                '--limit',
                '1',
                '--start-time',
                String(now.getTime()),
            ],
        ],
        [
            'tag:GetResources',
            [
                'resourcegroupstaggingapi',
                'get-resources',
                '--tag-filters',
                'Key=scenario-run',
                '--resources-per-page',
                '1',
            ],
        ],
    ]
}

async function missingPermissions(controller: Controller, profile: CloudProfile): Promise<string[]> {
    const missing: string[] = []
    for (const [action, args] of probesOf(profile, controller.now())) {
        try {
            await controller.aws.call(args)
        } catch (error) {
            if (error instanceof AwsError && DENIED.includes(error.code ?? '')) {
                missing.push(`Missing permission ${action}: ${error.stderr.trim()}`)
            }
        }
    }
    return missing
}

async function unorderable({ aws }: Controller, { engineVersion, writerClass }: CloudProfile): Promise<string[]> {
    const problems: string[] = []
    for (const instanceClass of [writerClass, SERVERLESS_CLASS]) {
        const { OrderableDBInstanceOptions } = (await aws.call([
            'rds',
            'describe-orderable-db-instance-options',
            '--engine',
            'aurora-postgresql',
            '--engine-version',
            engineVersion,
            '--db-instance-class',
            instanceClass,
            '--max-items',
            '1',
        ])) as { OrderableDBInstanceOptions: unknown[] }
        if (OrderableDBInstanceOptions.length === 0) {
            problems.push(`${instanceClass} is not orderable for aurora-postgresql ${engineVersion} in us-east-1.`)
        }
    }
    return problems
}

export async function admit(
    controller: Controller,
    profile: CloudProfile
): Promise<{ admitted: Admitted } | { problems: string[] }> {
    const { aws, origin, now } = controller
    const problems: string[] = []
    const identity = (await aws.call(['sts', 'get-caller-identity'])) as { Account: string; Arn: string }
    if (identity.Account !== profile.account) {
        problems.push(`The credentials are for account ${identity.Account}, and the profile names ${profile.account}.`)
    }
    problems.push(...(await missingPermissions(controller, profile)))

    const needed = new Date(
        now().getTime() + TTL_HOURS * HOUR_S * 1000 + durationMs(profile.admission.teardownAllowance)
    )
    const session = await sessionOf(controller)
    if ('problem' in session) {
        problems.push(session.problem)
    } else if ('unknown' in session) {
        problems.push('The credentials have no known expiry; use an Access Elevator profile with an SSO session.')
    } else if ('refreshable' in session) {
        controller.warn(
            'The SSO session refreshes its token, so its end cannot be read here. If it ends before the run, the stack-delete schedules still remove the stack.'
        )
    } else if (session.endsAt < needed) {
        problems.push(
            `The credentials expire at ${session.endsAt.toISOString()}, before the run and its teardown end at ${needed.toISOString()}.`
        )
    }

    problems.push(...(await unorderable(controller, profile)))
    const commit = origin.head()
    if (!(await origin.published(commit))) {
        problems.push(`Commit ${commit} is not on PostHog/posthog, so the run host cannot check it out. Push it first.`)
    }
    if (printEstimate(controller, profile) > CAP_USD) {
        problems.push(`The admitted estimate is over the $${CAP_USD} cap.`)
    }
    return problems.length > 0 ? { problems } : { admitted: { owner: identity.Arn, commit } }
}
