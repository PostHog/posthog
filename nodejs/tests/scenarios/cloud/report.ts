import { createHash } from 'crypto'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'

import { EXIT_CODE, Status } from '../runner/status'
import { SCHEMA_VERSION, ScorecardProperties } from '../scorecard/scorecard'
import { publish } from '../scorecard/write'
import { Controller, HOURS_PER_MONTH, dollars } from './admission'
import { Aws } from './aws'
import { Manifest, evidenceOf, keyOf } from './lease'
import { CloudProfile, RunInputs } from './profile'
import { receiptsOf } from './teardown'

export type RunEnd = { exitCode: number; reasons: string[]; teardownClean: boolean }

type Minute = { at: number; max?: number; avg?: number }

type Capacity = { minutes: Minute[]; gaps: number[] }

const CARD = 'cyclotron-failover-under-load'
const FAILOVER_VALVE = 'pg.failover'
const ENVIRONMENT_KIND = 'run-host'
const TARGET = 'cloud'
const MIN_ACU = 1
const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const ENHANCED_MONITORING = 'RDSOSMetrics'
const DEVIATIONS = [
    'team skew is not modelled',
    'active payload sizes are not modelled',
    'table, index and TOAST bytes are a fresh bulk load, not prod allocation',
]
const EXCLUDED = ['data transfer', 'S3 requests', 'Enhanced Monitoring log ingestion']

const HostScorecard = z.object({
    timeline: z.array(z.object({ valve: z.string(), requestedAt: z.string() }).passthrough()),
    event: z.object({ status: z.enum(['passed', 'failed', 'invalid']) }).catchall(z.unknown()),
})

const MetricData = z.object({
    MetricDataResults: z.array(
        z.object({ Id: z.enum(['max', 'avg']), Timestamps: z.array(z.string()), Values: z.array(z.number()) })
    ),
})

const LogPage = z.object({ events: z.array(z.unknown()), nextToken: z.string().optional() })

const minuteOf = (at: number): number => at - (at % MINUTE_MS)

const iso = (at: number): string => new Date(at).toISOString()

async function hostScorecardOf(
    evidence: ReturnType<typeof evidenceOf>,
    runId: string
): Promise<z.infer<typeof HostScorecard>> {
    const keys = (await evidence.keys(keyOf(runId, 'evidence/run/'))).filter((key) => key.endsWith('/scorecard.json'))
    if (keys.length !== 1) {
        throw new Error(`the host uploaded ${keys.length} runner scorecards, not one`)
    }
    return HostScorecard.parse(parseJSON(await evidence.get(keys[0])))
}

async function capacityOf(aws: Aws, readerId: string, from: number, to: number): Promise<Capacity> {
    const queries = Object.entries({ max: 'Maximum', avg: 'Average' }).map(([Id, Stat]) => ({
        Id,
        MetricStat: {
            Metric: {
                Namespace: 'AWS/RDS',
                MetricName: 'ServerlessDatabaseCapacity',
                Dimensions: [{ Name: 'DBInstanceIdentifier', Value: readerId }],
            },
            Period: 60,
            Stat,
        },
    }))
    const { MetricDataResults } = MetricData.parse(
        await aws.call([
            'cloudwatch',
            'get-metric-data',
            '--start-time',
            iso(minuteOf(from)),
            '--end-time',
            iso(minuteOf(to) + MINUTE_MS),
            '--scan-by',
            'TimestampAscending',
            '--metric-data-queries',
            JSON.stringify(queries),
        ])
    )
    const byMinute = new Map<number, Minute>()
    for (const { Id, Timestamps, Values } of MetricDataResults) {
        Timestamps.forEach((timestamp, i) => {
            const at = Date.parse(timestamp)
            byMinute.set(at, { ...byMinute.get(at), at, [Id]: Values[i] })
        })
    }
    const minutes = [...byMinute.values()].sort((a, b) => a.at - b.at)
    const gaps: number[] = []
    for (let at = minutes[0]?.at ?? 0; at <= (minutes.at(-1)?.at ?? -1); at += MINUTE_MS) {
        const minute = byMinute.get(at)
        if (minute?.max === undefined || minute.avg === undefined) {
            gaps.push(at)
        }
    }
    return { minutes, gaps }
}

async function keepEnhancedMonitoring(
    aws: Aws,
    evidence: ReturnType<typeof evidenceOf>,
    runId: string,
    from: number,
    to: number
): Promise<number> {
    const instances = ['writer', 'reader'].map((role) => `$.instanceID = "scn-${runId}-${role}"`)
    let token: string | undefined
    let events = 0
    let page = 0
    do {
        const answer = LogPage.parse(
            await aws.call([
                'logs',
                'filter-log-events',
                '--log-group-name',
                ENHANCED_MONITORING,
                '--start-time',
                String(from),
                '--end-time',
                String(to),
                '--filter-pattern',
                `{ (${instances.join(') || (')}) }`,
                '--no-paginate',
                ...(token ? ['--next-token', token] : []),
            ])
        )
        if (answer.events.length > 0) {
            const name = `capacity/${ENHANCED_MONITORING.toLowerCase()}/${String(page++).padStart(6, '0')}.json`
            await evidence.put(keyOf(runId, name), JSON.stringify(answer.events))
        }
        events += answer.events.length
        token = answer.nextToken
    } while (token)
    return events
}

function judgeCapacity({ minutes }: Capacity, t0: number): { scalars: Record<string, number | null>; reason?: string } {
    const t0Minute = minuteOf(t0)
    const maxima = minutes.flatMap(({ at, max }) => (max === undefined ? [] : [{ at, max }]))
    const before = minutes.flatMap(({ at, avg, max = avg }) =>
        at < t0Minute && max !== undefined ? [{ at, max }] : []
    )
    const after = maxima.filter(({ at }) => at >= t0Minute)
    const peak = after.reduce<{ at: number; max: number } | undefined>(
        (top, minute) => (top && top.max >= minute.max ? top : minute),
        undefined
    )
    const scalars = {
        acu_pre_t0_max: before.length > 0 ? Math.max(...before.map(({ max }) => max)) : null,
        acu_t0_minute_max: maxima.find(({ at }) => at === t0Minute)?.max ?? null,
        acu_peak: peak?.max ?? null,
        acu_seconds_to_peak: peak ? (peak.at - t0Minute) / 1000 : null,
    }
    if (before.length === 0) {
        return { scalars, reason: 'no reader capacity before T0' }
    }
    const above = before.filter(({ max }) => max > MIN_ACU)
    return above.length === 0
        ? { scalars }
        : { scalars, reason: `reader above 1 ACU before T0 (${above.map(({ at }) => iso(at)).join(', ')})` }
}

function costOf(profile: CloudProfile, hours: number, capacity: Capacity | undefined): [string, number][] {
    const { rates, allowances } = profile.admission
    const months = hours / HOURS_PER_MONTH
    const acuHours = (capacity?.minutes ?? []).reduce((sum, { avg }) => sum + (avg ?? 0) / 60, 0)
    const missing = capacity === undefined ? 'capacity unread' : `${capacity.gaps.length} minutes missing`
    return [
        [`writer ${profile.writerClass}, ${hours.toFixed(2)} h`, hours * rates.writerPerHour],
        [`reader, ${acuHours.toFixed(2)} ACU-hours, ${missing}`, acuHours * rates.acuPerHour],
        [`host ${profile.host.class}, ${hours.toFixed(2)} h`, hours * rates.hostPerHour],
        [`Aurora storage, ${allowances.storageGb} GB bound`, allowances.storageGb * rates.storagePerGbMonth * months],
        [`host EBS, ${profile.host.ebsGb} GB`, profile.host.ebsGb * rates.ebsPerGbMonth * months],
    ]
}

function environmentOf(profile: CloudProfile, manifest: Manifest, runnerFingerprint: unknown) {
    const environment = {
        environment_kind: ENVIRONMENT_KIND,
        writer_class: profile.writerClass,
        reader_acu_min: profile.readerAcu.min,
        reader_acu_max: profile.readerAcu.max,
        host_class: profile.host.class,
        engine_version: profile.engineVersion,
        pooler_replicas: profile.pooler.replicas,
        runner_profile_hash: manifest.inputs['runner-profile.yaml'],
        deviations: DEVIATIONS,
    }
    const fingerprint = createHash('sha256')
        .update(JSON.stringify([environment, profile.pooler, runnerFingerprint ?? null]))
        .digest('hex')
    return { ...environment, cloud_profile_hash: manifest.inputs['cloud-profile.yaml'], fingerprint }
}

async function attempt<T>(reasons: string[], what: string, work: () => Promise<T>): Promise<T | undefined> {
    try {
        return await work()
    } catch (error) {
        reasons.push(`${what}: ${(error as Error).message}`)
        return undefined
    }
}

export async function report(
    controller: Controller,
    { profile }: RunInputs,
    manifest: Manifest,
    end: RunEnd
): Promise<number> {
    const evidence = evidenceOf(controller.aws, profile.baseline.evidenceBucket)
    const { runId } = manifest
    const from = Date.parse(manifest.createdAt)
    const to = controller.now().getTime()
    const reasons = [...end.reasons]
    const host = await attempt(reasons, 'could not read the runner scorecard', () => hostScorecardOf(evidence, runId))
    const t0 = host?.timeline.find(({ valve }) => valve === FAILOVER_VALVE)?.requestedAt
    if (host?.event.status === 'passed' && !t0) {
        reasons.push(`the runner recorded no ${FAILOVER_VALVE}, so the reader was not judged`)
    }
    const capacity = await attempt(reasons, 'could not read the reader capacity', () =>
        capacityOf(controller.aws, `scn-${runId}-reader`, from, to)
    )
    const judged = capacity && t0 ? judgeCapacity(capacity, Date.parse(t0)) : undefined
    if (judged?.reason) {
        reasons.push(judged.reason)
    }
    const enhancedMonitoringEvents = await keepEnhancedMonitoring(controller.aws, evidence, runId, from, to).catch(
        (error: Error) => {
            controller.warn(`Could not keep the ${ENHANCED_MONITORING} events of run ${runId}: ${error.message}`)
            return null
        }
    )
    const receipt = (await receiptsOf(evidence, manifest).catch(() => [])).at(-1)
    const cost = costOf(profile, (to - from) / HOUR_MS, capacity)
    const costItems = cost.map(([item, usd]) => `${item}: ${dollars(usd)}`)
    const status: Status = reasons.length > 0 || !host ? 'invalid' : host.event.status
    const environment = environmentOf(profile, manifest, host?.event.fingerprint)
    const properties: ScorecardProperties = {
        schema_version: SCHEMA_VERSION,
        card_id: CARD,
        ...host?.event,
        ...environment,
        run_id: runId,
        origin: 'cloud-manual',
        target: TARGET,
        started_at: manifest.createdAt,
        status,
        status_reason: reasons.length > 0 ? reasons.join('; ') : String(host?.event.status_reason ?? ''),
        ended_at: iso(to),
        duration_s: (to - from) / 1000,
        evidence_dir: `s3://${evidence.name}/${keyOf(runId, 'evidence/')}`,
        t0_at: t0 ?? null,
        ...judged?.scalars,
        acu_gaps: capacity?.gaps.map(iso) ?? [],
        enhanced_monitoring_events: enhancedMonitoringEvents,
        teardown_clean: end.teardownClean,
        teardown_leftovers: (receipt?.resources ?? [])
            .filter(({ state }) => state !== 'gone')
            .map(({ type, id, state }) => `${type} ${id}: ${state}`),
        cost_estimate_usd: Number(cost.reduce((sum, [, usd]) => sum + usd, 0).toFixed(2)),
        cost_estimate_items: costItems,
        cost_estimate_excluded: EXCLUDED,
    }
    const key = keyOf(runId, 'scorecard.json')
    controller.print(`Cost estimate, excluding ${EXCLUDED.join(', ')}:`)
    costItems.forEach((item) => controller.print(`  ${item}`))
    const kept = await evidence.put(key, JSON.stringify(properties)).then(
        () => {
            controller.print(`Kept the ${status} scorecard at s3://${evidence.name}/${key}.`)
            return true
        },
        (error: Error) => {
            controller.warn(`Could not keep the scorecard at s3://${evidence.name}/${key}: ${error.message}`)
            return false
        }
    )
    const written = await publish(properties, controller.env, new AbortController().signal)
    if (written.recorded) {
        controller.print('Published the scorecard to Scenario runs.')
    } else if (written.problem) {
        controller.warn(`Could not publish the scorecard to Scenario runs: ${written.problem}`)
    } else {
        controller.print('Scenario runs credentials are not set, so the scorecard is not published.')
    }
    if (written.problem || (!kept && !written.recorded)) {
        return EXIT_CODE.writeFailed
    }
    return status === 'invalid' ? EXIT_CODE.invalid : end.exitCode
}
