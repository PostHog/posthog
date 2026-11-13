import { randomUUID } from 'crypto'
import { readFileSync, writeFileSync } from 'fs'
import { parse } from 'yaml'

import { parseJSON } from '~/common/utils/json-parse'

import { Aws, AwsError } from './aws'

type Schedule = { expression: string; target: { Arn: string; RoleArn: string; Input: string } }

type Resource = {
    logicalId: string
    type: string
    id: string
    arn: string
    state: string
    runTag?: string
    clusterResourceId?: string
    secretArn?: string
    rdsClusterArn?: string
    clusterId?: string
    createdAt?: number
    image?: string
    seeded?: boolean
}

type Command = {
    id: string
    instanceId: string
    script: string
    sentAt: number
    settlesAt: number
    status: string
    code: number
    undelivered?: boolean
}

type Card = {
    runId: string
    instanceId: string
    startedAt: number
    endsAt: number
    exitCode: number
    reportsDone: boolean
}

export type ReaderMinute = { minute: number; max?: number; avg?: number }

type MetricQuery = {
    Id: string
    MetricStat: {
        Metric: { Namespace: string; MetricName: string; Dimensions?: { Name: string; Value: string }[] }
        Period: number
        Stat: string
    }
}

type Stack = {
    name: string
    arn: string
    token: string
    status: string
    settlesAt: number
    runTag?: string
    parameters: Record<string, string>
    template: {
        Parameters: Record<string, { Type: string }>
        Resources: Record<string, { Type: string; Condition?: string; Properties: Record<string, unknown> }>
    }
    resources: Resource[]
}

const DELETED_STATES = new Set(['gone', 'terminated', 'deleted'])
const MINUTE_MS = 60_000
const SECRET_LISTING_LAG_MS = 5 * MINUTE_MS
const BACKUP = 'AWS::RDS::DBClusterAutomatedBackup'
const SNAPSHOT = 'AWS::RDS::DBClusterSnapshot'
const EXIT_INVALID = 2
const INVOCATION_LAG_MS = 20_000
const STOP_TIMEOUT_MS = 5 * MINUTE_MS
const DEFAULT_DELIVERY_TIMEOUT_S = 3600
const FAILOVER_AFTER_MS = 15 * MINUTE_MS
const LOG_PAGE_EVENTS = 2
const EVENTS_PER_INSTANCE = 3
const STATUSES = ['passed', 'failed', 'invalid', 'passed']
const DEFAULT_READER_ACU: ReaderMinute[] = [
    ...[-3, -2, -1].map((minute) => ({ minute, max: 1, avg: 1 })),
    { minute: 0, max: 2, avg: 1.5 },
    ...[1, 2, 3].map((minute) => ({ minute, max: 6, avg: 5 })),
]
const TAKES_MS: Record<string, number> = {
    CREATE_IN_PROGRESS: MINUTE_MS / 4,
    UPDATE_IN_PROGRESS: 10 * MINUTE_MS,
    DELETE_IN_PROGRESS: MINUTE_MS / 4,
}

export type FakeCloudOptions = {
    now: () => Date
    account?: string
    expiration?: Date | string | null
    role?: string
    session?: string
    ssoSession?: string
    sourceProfile?: string
    orderable?: string[]
    denied?: string[]
    host?: 'ready' | 'failed' | 'silent'
    deleteFailures?: number
    deleteTakesMs?: number
    rollsBack?: 'create' | 'update'
    outlives?: string[]
    seed?: { exitCode?: number; takesMs?: number }
    card?: {
        exitCode?: number
        takesMs?: number
        ignoresStop?: boolean
        uploadFails?: boolean
        diesAfterMs?: number
        runnerStatus?: string
    }
    probe?: 'lost' | 'timedOut'
    agent?: 'offline'
    readerAcu?: ReaderMinute[]
}

const ACTION_OF: Record<string, string> = {
    's3api list-objects-v2': 's3:ListBucket',
    'resourcegroupstaggingapi get-resources': 'tag:GetResources',
    'rds describe-db-instances': 'rds:DescribeDBInstances',
}

const IAM_PREFIX: Record<string, string> = { s3api: 's3', sts: 'sts', configure: 'sts' }

function actionOf(service: string, operation: string): string {
    const pascal = operation.replace(/(^|-)([a-z0-9])/g, (_, __, letter: string) => letter.toUpperCase())
    return ACTION_OF[`${service} ${operation}`] ?? `${IAM_PREFIX[service] ?? service}:${pascal}`
}

function flagsOf(args: string[]): { flags: Map<string, string>; positionals: string[] } {
    const flags = new Map<string, string>()
    const positionals: string[] = []
    for (let i = 0; i < args.length; i++) {
        if (args[i].startsWith('--') && (args[i + 1] ?? '--').startsWith('--')) {
            flags.set(args[i].slice(2), '')
        } else if (args[i].startsWith('--')) {
            flags.set(args[i].slice(2), args[i + 1])
            i++
        } else {
            positionals.push(args[i])
        }
    }
    return { flags, positionals }
}

function serviceError(operation: string, code: string, message: string): AwsError {
    const pascal = actionOf('', operation).slice(1)
    return new AwsError(
        [operation],
        254,
        `An error occurred (${code}) when calling the ${pascal} operation: ${message}`
    )
}

function atOf(expression: string): number {
    return Date.parse(`${/^at\((.+)\)$/.exec(expression)![1]}Z`)
}

export class FakeCloud implements Aws {
    readonly account: string
    readonly objects = new Map<string, string>()
    readonly schedules = new Map<string, Schedule>()
    readonly deleteStackRequests: { stackName: string; at: string }[] = []
    expiration: Date | string | null
    role: string
    session: string
    ssoSession: string | undefined
    readonly orderable: string[]
    readonly denied: Set<string>
    readonly stacks = new Map<string, Stack>()
    readonly resources: Resource[] = []
    readonly parameterStore = new Map<string, string>()
    readonly untyped: string[] = []
    private readonly commands: Command[] = []
    private card: Card | undefined
    readonly failovers = new Map<string, number>()
    private deleteFailures: number
    private readonly failures = new Map<string, { from: number; to: number }>()
    private readonly conditions = new Map<string, (args: string[]) => boolean>()
    private readonly lostResponses = new Map<string, number>()
    private readonly calls = new Map<string, number>()
    private readonly hooks = new Map<string, () => void>()
    private hidesCreation: () => boolean = () => false

    constructor(private readonly options: FakeCloudOptions) {
        this.account = options.account ?? '000000000000'
        this.expiration = options.expiration === undefined ? null : options.expiration
        this.role = options.role ?? 'scenario-run-controller'
        this.session = options.session ?? 'person'
        this.ssoSession = options.ssoSession
        this.orderable = options.orderable ?? ['db.r8g.2xlarge', 'db.serverless']
        this.denied = new Set(options.denied ?? [])
        this.deleteFailures = options.deleteFailures ?? 0
        this.parameterStore.set('/test/ubuntu/ami-id', 'ami-0000000000000000a')
    }

    failOnCall(operation: string, nth: number = 1, times: number = 1): void {
        const from = (this.calls.get(operation) ?? 0) + nth
        this.failures.set(operation, { from, to: from + times })
    }

    failWhen(operation: string, applies: (args: string[]) => boolean): void {
        this.conditions.set(operation, applies)
    }

    heal(): void {
        this.failures.clear()
        this.conditions.clear()
    }

    hideCreationWhile(applies: () => boolean): void {
        this.hidesCreation = applies
    }

    loseResponseOf(operation: string, nth: number = 1): void {
        this.lostResponses.set(operation, (this.calls.get(operation) ?? 0) + nth)
    }

    beforeCall(operation: string, hook: () => void): void {
        this.hooks.set(operation, hook)
    }

    billable(): string[] {
        return this.resources.filter(({ state }) => !DELETED_STATES.has(state)).map(({ type, id }) => `${type} ${id}`)
    }

    call(args: string[]): Promise<unknown> {
        return Promise.resolve().then(() => this.handle(args))
    }

    text(args: string[]): Promise<string> {
        return Promise.resolve().then(() => {
            const answer = this.handle(args)
            return typeof answer === 'string' ? answer : JSON.stringify(answer)
        })
    }

    tick(): void {
        const now = this.options.now().getTime()
        if (this.card && this.card.endsAt <= now) {
            this.finishCard(this.card.exitCode)
        }
        for (const stack of [...this.stacks.values()].filter(({ settlesAt }) => settlesAt <= now)) {
            this.settleStack(stack.name)
        }
        for (const [name, schedule] of this.schedules) {
            if (atOf(schedule.expression) <= now) {
                const { StackName } = parseJSON(schedule.target.Input) as { StackName: string }
                this.deleteStackRequests.push({
                    stackName: StackName,
                    at: new Date(atOf(schedule.expression)).toISOString(),
                })
                this.requestStackDeletion(StackName)
                this.settleStack(StackName)
                this.schedules.delete(name)
            }
        }
    }

    private handle(args: string[]): unknown {
        this.tick()
        const [service, operation, ...rest] = args
        const { flags, positionals } = flagsOf(rest)
        const count = (this.calls.get(operation) ?? 0) + 1
        this.calls.set(operation, count)
        this.hooks.get(operation)?.()
        const failing = this.failures.get(operation)
        if ((failing && count >= failing.from && count < failing.to) || this.conditions.get(operation)?.(rest)) {
            throw serviceError(operation, 'InternalFailure', 'injected by the fake cloud')
        }
        const action = actionOf(service, operation)
        if (this.denied.has(action)) {
            throw serviceError(operation, 'AccessDeniedException', `User is not authorized to perform: ${action}`)
        }
        const answer = this.answer(service, operation, flags, positionals)
        if (this.lostResponses.get(operation) === count) {
            throw new AwsError([service, operation], 255, 'Connection was closed before we received a valid response')
        }
        return answer
    }

    private parametersOf(flags: Map<string, string>, template: Stack['template']): Record<string, string> {
        const listed = parseJSON(flags.get('parameters')!) as { ParameterKey: string; ParameterValue: string }[]
        return Object.fromEntries(
            listed.map(({ ParameterKey, ParameterValue }) => {
                const fromStore = template.Parameters[ParameterKey].Type.startsWith('AWS::SSM::Parameter::Value')
                return [ParameterKey, fromStore ? this.parameterStore.get(ParameterValue)! : ParameterValue]
            })
        )
    }

    private provision(stack: Stack): void {
        const sub = (value: unknown): string =>
            String(value).replace(/\$\{(\w+)\}/g, (_, name: string) => stack.parameters[name])
        const id = stack.parameters.RunId
        const runTag = stack.runTag
        for (const [logicalId, { Type, Condition, Properties }] of Object.entries(stack.template.Resources)) {
            const wanted = Condition === undefined || stack.parameters[Condition] === 'true'
            const current = stack.resources.filter(
                (resource) => resource.logicalId.startsWith(logicalId) && !DELETED_STATES.has(resource.state)
            )
            const replaced =
                Type === 'AWS::EC2::Instance' &&
                current.some(({ type, image }) => type === Type && image !== stack.parameters.HostImage)
            if (!wanted || (current.length > 0 && !replaced)) {
                continue
            }
            this.removeResources(stack, (resource) => current.includes(resource))
            const identifier = (property: string): string =>
                sub((Properties[property] as { 'Fn::Sub': string })['Fn::Sub'])
            const created: Resource[] = []
            if (Type === 'AWS::RDS::DBCluster') {
                const clusterId = identifier('DBClusterIdentifier')
                const secret: Resource = {
                    logicalId: `${logicalId}Secret`,
                    type: 'AWS::SecretsManager::Secret',
                    id: `arn:aws:secretsmanager:us-east-1:${this.account}:secret:rds!cluster-${randomUUID()}`,
                    arn: '',
                    state: 'active',
                }
                secret.arn = secret.id
                secret.rdsClusterArn = `arn:aws:rds:us-east-1:${this.account}:cluster:${clusterId}`
                secret.createdAt = this.options.now().getTime()
                created.push(
                    {
                        logicalId,
                        type: Type,
                        id: clusterId,
                        arn: `arn:aws:rds:us-east-1:${this.account}:cluster:${clusterId}`,
                        state: 'available',
                        runTag,
                        clusterResourceId: `cluster-${randomUUID()}`,
                        secretArn: secret.arn,
                    },
                    secret
                )
            } else if (Type === 'AWS::RDS::DBInstance') {
                const instanceId = identifier('DBInstanceIdentifier')
                created.push({
                    logicalId,
                    type: Type,
                    id: instanceId,
                    arn: `arn:aws:rds:us-east-1:${this.account}:db:${instanceId}`,
                    state: 'available',
                    runTag,
                    seeded: this.backlogSeeded(),
                })
            } else if (Type === 'AWS::EC2::Instance') {
                const instanceId = `i-${randomUUID().replace(/-/g, '').slice(0, 17)}`
                const volumeId = `vol-${randomUUID().replace(/-/g, '').slice(0, 17)}`
                created.push(
                    {
                        logicalId,
                        type: Type,
                        id: instanceId,
                        arn: `arn:aws:ec2:us-east-1:${this.account}:instance/${instanceId}`,
                        state: 'running',
                        runTag,
                        image: stack.parameters.HostImage,
                    },
                    {
                        logicalId: `${logicalId}Volume`,
                        type: 'AWS::EC2::Volume',
                        id: volumeId,
                        arn: `arn:aws:ec2:us-east-1:${this.account}:volume/${volumeId}`,
                        state: 'in-use',
                        runTag: Properties.PropagateTagsToVolumeOnCreation === true ? runTag : undefined,
                    }
                )
                const marker = { ready: 'host/ready', failed: 'host/failed', silent: undefined }[
                    this.options.host ?? 'ready'
                ]
                if (marker && this.options.rollsBack !== 'create') {
                    this.objects.set(`runs/${id}/${marker}`, '{}')
                }
            } else {
                throw new Error(`the fake cloud does not model ${Type}`)
            }
            stack.resources.push(...created)
            this.resources.push(...created)
        }
    }

    private hostRunning(instanceId: string): boolean {
        return this.resources.some(
            ({ type, id, state }) => type === 'AWS::EC2::Instance' && id === instanceId && state === 'running'
        )
    }

    private backlogSeeded(): boolean {
        const now = this.options.now().getTime()
        return this.commands.some(
            ({ script, status, settlesAt }) =>
                script.includes('host-prepare.sh') && status === 'Success' && settlesAt <= now
        )
    }

    private finishCard(exitCode: number): void {
        const card = this.card!
        this.card = undefined
        if (!this.hostRunning(card.instanceId) || !card.reportsDone) {
            return
        }
        const failoverAt = card.startedAt + FAILOVER_AFTER_MS
        if (this.options.now().getTime() >= failoverAt) {
            this.failovers.set(card.runId, failoverAt)
        }
        const uploaded = !this.options.card?.uploadFails
        if (uploaded) {
            const runnerRunId = randomUUID()
            const files = {
                'card.log': `exit ${exitCode}\n`,
                [`run/${runnerRunId}/scorecard.json`]: this.runnerScorecard(card, runnerRunId, exitCode),
            }
            const sums = Object.keys(files)
                .map((file) => `${'0'.repeat(64)}  ./${file}`)
                .join('\n')
            Object.entries(files).forEach(([file, body]) =>
                this.objects.set(`runs/${card.runId}/evidence/${file}`, body)
            )
            this.objects.set(`runs/${card.runId}/evidence/SHA256SUMS`, `${sums}\n`)
        }
        this.objects.set(`runs/${card.runId}/host/done`, JSON.stringify({ exitCode, uploaded }))
    }

    private runnerScorecard(card: Card, runnerRunId: string, exitCode: number): string {
        const status = this.options.card?.runnerStatus ?? STATUSES[exitCode] ?? 'invalid'
        const statusReason = status === 'passed' ? '' : `the card ended ${status}`
        const failoverAt = this.failovers.get(card.runId)
        const timeline =
            failoverAt === undefined
                ? []
                : [
                      {
                          valve: 'pg.failover',
                          target: 'cyclotron',
                          requestedAt: new Date(failoverAt).toISOString(),
                          appliedAt: new Date(failoverAt + 5_000).toISOString(),
                      },
                  ]
        const startedAt = new Date(card.startedAt).toISOString()
        const endedAt = this.options.now().toISOString()
        return JSON.stringify({
            runId: runnerRunId,
            status,
            statusReason,
            timeline,
            startedAt,
            endedAt,
            event: {
                schema_version: 1,
                run_id: runnerRunId,
                card_id: 'cyclotron-failover-under-load',
                origin: 'local-agent',
                target: 'local',
                fingerprint: 'f'.repeat(64),
                status,
                status_reason: statusReason,
                started_at: startedAt,
                ended_at: endedAt,
                m_writer_recovery_s: 42,
                valve_timeline: timeline,
                evidence_dir: `/opt/scenario/cache/posthog-scenarios/${runnerRunId}`,
            },
        })
    }

    private readerCapacity({ Id, MetricStat: { Metric, Period, Stat } }: MetricQuery, from: number, to: number) {
        const instance = (Metric.Dimensions ?? []).find(({ Name }) => Name === 'DBInstanceIdentifier')?.Value ?? ''
        const runId = /^scn-(.+)-reader$/.exec(instance)?.[1]
        const measured =
            Metric.Namespace === 'AWS/RDS' && Metric.MetricName === 'ServerlessDatabaseCapacity' && Period === 60
        const failoverAt = runId && measured ? this.failovers.get(runId) : undefined
        const t0Minute = failoverAt === undefined ? 0 : failoverAt - (failoverAt % MINUTE_MS)
        const points = (failoverAt === undefined ? [] : (this.options.readerAcu ?? DEFAULT_READER_ACU))
            .map(({ minute, max, avg }) => ({
                at: t0Minute + minute * MINUTE_MS,
                value: { Maximum: max, Average: avg, SampleCount: 60 }[Stat],
            }))
            .filter(({ at, value }) => at >= from && at < to && value !== undefined)
        return {
            Id,
            Label: Id,
            Timestamps: points.map(({ at }) => new Date(at).toISOString()),
            Values: points.map(({ value }) => value),
            StatusCode: 'Complete',
        }
    }

    private enhancedMonitoring(flags: Map<string, string>): unknown {
        const from = Number(flags.get('start-time'))
        const pattern = flags.get('filter-pattern') ?? ''
        const events =
            flags.get('log-group-name') === 'RDSOSMetrics'
                ? this.resources
                      .filter(({ type, id }) => type === 'AWS::RDS::DBInstance' && pattern.includes(`"${id}"`))
                      .flatMap(({ id }) =>
                          Array.from({ length: EVENTS_PER_INSTANCE }, (_, second) => ({
                              logStreamName: `db-${id}`,
                              timestamp: from + second * 1000,
                              message: JSON.stringify({ instanceID: id, second }),
                          }))
                      )
                : []
        if (!flags.has('no-paginate')) {
            return { events }
        }
        const offset = Number(flags.get('next-token') ?? 0)
        const next = offset + LOG_PAGE_EVENTS
        return {
            events: events.slice(offset, next),
            ...(next < events.length ? { nextToken: String(next) } : {}),
        }
    }

    private sendCommand(flags: Map<string, string>, operation: string): string {
        const instanceId = flags.get('instance-ids')!
        const { commands, executionTimeout } = parseJSON(flags.get('parameters')!) as {
            commands: string[]
            executionTimeout?: string[]
        }
        if (flags.get('document-name') !== 'AWS-RunShellScript' || executionTimeout === undefined) {
            throw new Error('the fake cloud models only shell commands with an execution timeout')
        }
        if (!this.hostRunning(instanceId)) {
            throw serviceError(operation, 'InvalidInstanceId', `${instanceId} is not a managed instance`)
        }
        const now = this.options.now().getTime()
        const script = commands.join('\n')
        const timeoutMs = Number(executionTimeout[0]) * 1000
        const runId = /SCENARIO_RUN_ID='?([\w-]+)/.exec(script)?.[1]
        const command: Command = {
            id: randomUUID(),
            instanceId,
            script,
            sentAt: now,
            settlesAt: now + MINUTE_MS / 4,
            status: 'Success',
            code: 0,
        }
        if (this.options.agent === 'offline') {
            const deliveryMs = Number(flags.get('timeout-seconds') ?? DEFAULT_DELIVERY_TIMEOUT_S) * 1000
            this.commands.push({
                ...command,
                settlesAt: now + deliveryMs + timeoutMs,
                status: 'TimedOut',
                code: -1,
                undelivered: true,
            })
            return command.id
        }
        if (script.includes('host-prepare.sh')) {
            const { exitCode = 0, takesMs = 10 * MINUTE_MS } = this.options.seed ?? {}
            command.settlesAt = now + Math.min(takesMs, timeoutMs)
            command.status = takesMs > timeoutMs ? 'TimedOut' : exitCode === 0 ? 'Success' : 'Failed'
            command.code = takesMs > timeoutMs ? -1 : exitCode
        } else if (script.includes('systemd-run') && script.includes('host-run-card.sh') && runId) {
            const { exitCode = 0, takesMs = 90 * MINUTE_MS, diesAfterMs } = this.options.card ?? {}
            this.objects.set(`runs/${runId}/host/started`, '{}')
            this.card =
                diesAfterMs === undefined
                    ? { runId, instanceId, startedAt: now, endsAt: now + takesMs, exitCode, reportsDone: true }
                    : {
                          runId,
                          instanceId,
                          startedAt: now,
                          endsAt: now + diesAfterMs,
                          exitCode: EXIT_INVALID,
                          reportsDone: false,
                      }
        } else if (script.includes('systemctl is-active')) {
            command.settlesAt = this.options.probe === 'lost' ? Infinity : command.settlesAt
            command.status = this.options.probe === 'timedOut' ? 'TimedOut' : this.card ? 'Success' : 'Failed'
            command.code = this.options.probe === 'timedOut' ? -1 : this.card ? 0 : 3
        } else if (script.includes('systemctl stop')) {
            const ignoresStop = this.options.card?.ignoresStop === true
            const stopsAt = now + (ignoresStop ? STOP_TIMEOUT_MS : MINUTE_MS)
            if (this.card && this.card.endsAt > stopsAt) {
                this.card.endsAt = stopsAt
                this.card.exitCode = EXIT_INVALID
                this.card.reportsDone = !ignoresStop
            }
            command.settlesAt = Math.max(command.settlesAt, this.card?.endsAt ?? now)
        } else {
            throw new Error(`the fake cloud does not model the host command ${script}`)
        }
        this.commands.push(command)
        return command.id
    }

    private invocation(flags: Map<string, string>, operation: string): unknown {
        const command = this.commands.find(
            ({ id, instanceId }) => id === flags.get('command-id') && instanceId === flags.get('instance-id')
        )
        const now = this.options.now().getTime()
        if (!command || now - command.sentAt < INVOCATION_LAG_MS) {
            throw serviceError(operation, 'InvocationDoesNotExist', 'no such invocation')
        }
        const settled = command.settlesAt <= now
        return {
            CommandId: command.id,
            InstanceId: command.instanceId,
            Status: settled ? command.status : command.undelivered ? 'Pending' : 'InProgress',
            ResponseCode: settled ? command.code : -1,
            StandardErrorContent: settled && command.code !== 0 ? 'the command failed on the host' : '',
        }
    }

    private requestStackDeletion(name: string): void {
        const stack = this.stacks.get(name)
        if (stack && !stack.status.startsWith('DELETE_COMPLETE')) {
            this.transition(stack, 'DELETE_IN_PROGRESS')
        }
    }

    private transition(stack: Stack, status: string): void {
        stack.status = status
        const takesMs = status === 'DELETE_IN_PROGRESS' ? this.options.deleteTakesMs : undefined
        stack.settlesAt = this.options.now().getTime() + (takesMs ?? TAKES_MS[status])
    }

    private settleStack(name: string): void {
        const stack = this.stacks.get(name)
        if (!stack) {
            return
        }
        stack.settlesAt = Infinity
        if (stack.status === 'CREATE_IN_PROGRESS' && this.options.rollsBack === 'create') {
            this.removeResources(stack, ({ type }) => !(this.options.outlives ?? []).includes(type))
            this.stacks.delete(name)
        } else if (stack.status === 'CREATE_IN_PROGRESS') {
            stack.status = 'CREATE_COMPLETE'
        } else if (stack.status === 'UPDATE_IN_PROGRESS' && this.options.rollsBack === 'update') {
            this.removeResources(stack, ({ logicalId }) => logicalId === 'Reader')
            stack.status = 'UPDATE_ROLLBACK_COMPLETE'
        } else if (stack.status === 'UPDATE_IN_PROGRESS') {
            stack.status = 'UPDATE_COMPLETE'
        } else if (stack.status === 'DELETE_IN_PROGRESS' && this.deleteFailures > 0) {
            this.deleteFailures--
            stack.status = 'DELETE_FAILED'
        } else if (stack.status === 'DELETE_IN_PROGRESS') {
            this.removeResources(stack, ({ type }) => !(this.options.outlives ?? []).includes(type))
            if ((this.options.outlives ?? []).includes(SNAPSHOT)) {
                this.resources.push(
                    ...stack.resources
                        .filter(({ type }) => type === 'AWS::RDS::DBCluster')
                        .map((cluster) => ({
                            logicalId: `${cluster.logicalId}Snapshot`,
                            type: SNAPSHOT,
                            id: `${cluster.id}-final`,
                            arn: `arn:aws:rds:us-east-1:${this.account}:cluster-snapshot:${cluster.id}-final`,
                            state: 'available',
                            clusterId: cluster.id,
                        }))
                )
            }
            if ((this.options.outlives ?? []).includes(BACKUP)) {
                this.resources.push(
                    ...stack.resources
                        .filter(({ type }) => type === 'AWS::RDS::DBCluster')
                        .map((cluster) => ({
                            logicalId: `${cluster.logicalId}Backup`,
                            type: BACKUP,
                            id: cluster.clusterResourceId!,
                            arn: '',
                            state: 'retained',
                            clusterId: cluster.id,
                        }))
                )
            }
            this.stacks.delete(name)
        }
    }

    private removeResources(stack: Stack, removed: (resource: Resource) => boolean): void {
        for (const resource of stack.resources.filter(removed)) {
            resource.state = resource.type === 'AWS::EC2::Instance' ? 'terminated' : 'gone'
        }
    }

    private creating(resource: Resource): boolean {
        return [...this.stacks.values()].some(
            ({ status, resources }) => status === 'CREATE_IN_PROGRESS' && resources.includes(resource)
        )
    }

    private liveResource(type: string, id: string, operation: string, code: string): Resource {
        const resource = this.resources.find((candidate) => candidate.type === type && candidate.id === id)
        if (!resource || resource.state === 'gone') {
            throw serviceError(operation, code, `${id} not found`)
        }
        return resource
    }

    private stackOf(operation: string, name: string): Stack {
        const stack = this.stacks.get(name)
        if (!stack) {
            throw serviceError(operation, 'ValidationError', `Stack with id ${name} does not exist`)
        }
        return stack
    }

    private configured(key: string, profile: string | undefined): string {
        const value =
            key === 'source_profile'
                ? this.options.sourceProfile
                : this.options.sourceProfile === undefined || profile === this.options.sourceProfile
                  ? this.ssoSession
                  : undefined
        if (value === undefined) {
            throw new AwsError(['configure', 'get', key], 1, '')
        }
        return value
    }

    private answer(service: string, operation: string, flags: Map<string, string>, positionals: string[]): unknown {
        switch (`${service} ${operation}`) {
            case 'sts get-caller-identity':
                return {
                    Account: this.account,
                    Arn: `arn:aws:sts::${this.account}:assumed-role/${this.role}/${this.session}`,
                    UserId: 'AROAEXAMPLE:person',
                }
            case 'configure get':
                return this.configured(positionals[0], flags.get('profile'))
            case 'configure export-credentials':
                return {
                    Version: 1,
                    AccessKeyId: 'ASIAEXAMPLE',
                    SecretAccessKey: 'example-secret',
                    SessionToken: 'example-token',
                    ...(this.expiration
                        ? {
                              Expiration:
                                  this.expiration instanceof Date ? this.expiration.toISOString() : this.expiration,
                          }
                        : {}),
                }
            case 'rds describe-orderable-db-instance-options':
                return {
                    OrderableDBInstanceOptions: this.orderable
                        .filter((instanceClass) => instanceClass === flags.get('db-instance-class'))
                        .map((instanceClass) => ({
                            Engine: flags.get('engine'),
                            EngineVersion: flags.get('engine-version'),
                            DBInstanceClass: instanceClass,
                        })),
                }
            case 'cloudformation describe-stacks': {
                const stack = this.stackOf(operation, flags.get('stack-name')!)
                return { Stacks: [{ StackName: stack.name, StackStatus: stack.status }] }
            }
            case 'cloudformation create-stack': {
                const name = flags.get('stack-name')!
                const existing = this.stacks.get(name)
                if (existing) {
                    if (existing.token !== flags.get('client-request-token')) {
                        throw serviceError(operation, 'AlreadyExistsException', `Stack [${name}] already exists`)
                    }
                    return { StackId: name }
                }
                if (flags.get('on-failure') !== 'DELETE' || !flags.get('role-arn')) {
                    throw new Error('the fake cloud models only stacks that delete on failure under a service role')
                }
                const template = parse(readFileSync(flags.get('template-body')!.replace(/^file:\/\//, ''), 'utf8'))
                const tags = parseJSON(flags.get('tags') ?? '[]') as { Key: string; Value: string }[]
                const stack: Stack = {
                    name,
                    arn: `arn:aws:cloudformation:us-east-1:${this.account}:stack/${name}/${randomUUID()}`,
                    token: flags.get('client-request-token')!,
                    status: 'CREATE_IN_PROGRESS',
                    settlesAt: this.options.now().getTime() + TAKES_MS.CREATE_IN_PROGRESS,
                    runTag: tags.find(({ Key }) => Key === 'scenario-run')?.Value,
                    parameters: this.parametersOf(flags, template),
                    template,
                    resources: [],
                }
                this.stacks.set(name, stack)
                this.provision(stack)
                return { StackId: name }
            }
            case 'cloudformation update-stack': {
                const stack = this.stackOf(operation, flags.get('stack-name')!)
                stack.parameters = this.parametersOf(flags, stack.template)
                this.transition(stack, 'UPDATE_IN_PROGRESS')
                this.provision(stack)
                return { StackId: stack.name }
            }
            case 'cloudformation delete-stack': {
                const status = this.stacks.get(flags.get('stack-name')!)?.status ?? ''
                if (/^UPDATE_.*IN_PROGRESS$/.test(status)) {
                    throw serviceError(
                        operation,
                        'ValidationError',
                        `Stack is in ${status} state and can not be deleted`
                    )
                }
                this.requestStackDeletion(flags.get('stack-name')!)
                return null
            }
            case 'cloudformation describe-stack-resources':
                return {
                    StackResources: this.stackOf(operation, flags.get('stack-name')!)
                        .resources.filter((resource) => !this.hidesCreation() && !this.creating(resource))
                        .filter(({ logicalId }) => !logicalId.endsWith('Volume') && !logicalId.endsWith('Secret'))
                        .map(({ logicalId, type, id }) => ({
                            LogicalResourceId: logicalId,
                            ResourceType: type,
                            PhysicalResourceId: id,
                        })),
                }
            case 'rds describe-db-clusters': {
                if (this.hidesCreation()) {
                    throw serviceError(operation, 'DBClusterNotFoundFault', 'The cluster is not visible yet')
                }
                const cluster = this.liveResource(
                    'AWS::RDS::DBCluster',
                    flags.get('db-cluster-identifier')!,
                    operation,
                    'DBClusterNotFoundFault'
                )
                return {
                    DBClusters: [
                        {
                            Status: cluster.state,
                            DbClusterResourceId: cluster.clusterResourceId,
                            MasterUserSecret: { SecretArn: cluster.secretArn },
                        },
                    ],
                }
            }
            case 'rds describe-db-instances':
                return {
                    DBInstances: [
                        {
                            DBInstanceStatus: this.liveResource(
                                'AWS::RDS::DBInstance',
                                flags.get('db-instance-identifier')!,
                                operation,
                                'DBInstanceNotFound'
                            ).state,
                        },
                    ],
                }
            case 'rds describe-db-cluster-snapshots': {
                const kept = this.resources.filter(({ type, state }) => type === SNAPSHOT && state !== 'gone')
                if (flags.has('db-cluster-snapshot-identifier')) {
                    const snapshot = kept.find(({ id }) => id === flags.get('db-cluster-snapshot-identifier'))
                    if (!snapshot) {
                        throw serviceError(operation, 'DBClusterSnapshotNotFoundFault', 'The snapshot was not found')
                    }
                    return { DBClusterSnapshots: [{ Status: snapshot.state }] }
                }
                return {
                    DBClusterSnapshots: kept
                        .filter(({ clusterId }) => clusterId === flags.get('db-cluster-identifier'))
                        .map(({ id }) => ({ DBClusterSnapshotIdentifier: id })),
                }
            }
            case 'rds describe-db-cluster-automated-backups': {
                const retained = this.resources.filter(({ type, state }) => type === BACKUP && state !== 'gone')
                if (flags.has('filters')) {
                    return {
                        DBClusterAutomatedBackups: retained
                            .filter(
                                ({ clusterId }) => flags.get('filters') === `Name=db-cluster-id,Values=${clusterId}`
                            )
                            .map(({ id, state }) => ({ DbClusterResourceId: id, Status: state })),
                    }
                }
                const backup = retained.find(({ id }) => id === flags.get('db-cluster-resource-id'))
                if (backup) {
                    return { DBClusterAutomatedBackups: [{ Status: backup.state }] }
                }
                throw serviceError(operation, 'DBClusterAutomatedBackupNotFoundFault', 'no retained backups')
            }
            case 'ec2 describe-instances': {
                if (!flags.has('instance-ids')) {
                    return { Reservations: [] }
                }
                const instance = this.liveResource(
                    'AWS::EC2::Instance',
                    flags.get('instance-ids')!,
                    operation,
                    'InvalidInstanceID.NotFound'
                )
                return { Reservations: [{ Instances: [{ State: { Name: instance.state } }] }] }
            }
            case 'ec2 describe-volumes':
                return {
                    Volumes: [
                        {
                            State: this.liveResource(
                                'AWS::EC2::Volume',
                                flags.get('volume-ids')!,
                                operation,
                                'InvalidVolume.NotFound'
                            ).state,
                        },
                    ],
                }
            case 'secretsmanager list-secrets': {
                const filters = [flags.get('filters'), ...positionals]
                return {
                    SecretList: this.resources
                        .filter(
                            ({ type, state, rdsClusterArn, createdAt }) =>
                                type === 'AWS::SecretsManager::Secret' &&
                                state !== 'gone' &&
                                this.options.now().getTime() - (createdAt ?? 0) >= SECRET_LISTING_LAG_MS &&
                                filters.includes('Key=tag-key,Values=aws:rds:primaryDBClusterArn') &&
                                filters.includes(`Key=tag-value,Values=${rdsClusterArn}`)
                        )
                        .map(({ id }) => ({ ARN: id })),
                }
            }
            case 'secretsmanager describe-secret': {
                const secret = this.resources.find(({ id }) => id === flags.get('secret-id'))
                if (!secret) {
                    throw serviceError(operation, 'ResourceNotFoundException', 'Secrets Manager cannot find the secret')
                }
                return secret.state === 'gone'
                    ? { ARN: secret.id, DeletedDate: '2026-03-02T00:00:00Z' }
                    : { ARN: secret.id }
            }
            case 'ssm send-command':
                return { Command: { CommandId: this.sendCommand(flags, operation) } }
            case 'ssm get-command-invocation':
                return this.invocation(flags, operation)
            case 'cloudwatch get-metric-data': {
                const queries = flags.has('metric-data-queries')
                    ? (parseJSON(flags.get('metric-data-queries')!) as MetricQuery[])
                    : []
                const [from, to] = ['start-time', 'end-time'].map((flag) => Date.parse(flags.get(flag) ?? ''))
                return { MetricDataResults: queries.map((query) => this.readerCapacity(query, from, to)) }
            }
            case 'logs filter-log-events':
                return this.enhancedMonitoring(flags)
            case 'resourcegroupstaggingapi get-resources': {
                const runId = /Values=(.+)$/.exec(flags.get('tag-filters') ?? '')?.[1]
                return {
                    ResourceTagMappingList: [
                        ...[...this.stacks.values()].filter(({ status }) => status !== 'CREATE_IN_PROGRESS'),
                        ...this.resources.filter((resource) => !this.creating(resource)),
                        ...(this.stacks.size > 0 ? this.untyped.map((arn) => ({ arn, runTag: runId })) : []),
                    ]
                        .filter((tagged) => tagged.runTag === runId)
                        .map(({ arn }) => ({ ResourceARN: arn })),
                }
            }
            case 'ssm get-parameter': {
                const value = this.parameterStore.get(flags.get('name')!)
                if (value === undefined) {
                    throw serviceError(operation, 'ParameterNotFound', `${flags.get('name')} not found`)
                }
                return { Parameter: { Name: flags.get('name'), Value: value } }
            }
            case 's3api put-object':
                this.objects.set(flags.get('key')!, readFileSync(flags.get('body')!, 'utf8'))
                return { ETag: '"etag"' }
            case 's3api get-object': {
                const body = this.objects.get(flags.get('key')!)
                if (body === undefined) {
                    throw serviceError(operation, 'NoSuchKey', 'The specified key does not exist.')
                }
                writeFileSync(positionals[0], body)
                return { ContentLength: body.length }
            }
            case 's3api delete-object':
                this.objects.delete(flags.get('key')!)
                return null
            case 's3api list-objects-v2': {
                const keys = [...this.objects.keys()].filter((key) => key.startsWith(flags.get('prefix') ?? '')).sort()
                return keys.length === 0 ? null : { Contents: keys.map((Key) => ({ Key })) }
            }
            case 'scheduler create-schedule': {
                const name = flags.get('name')!
                if (this.schedules.has(name)) {
                    throw serviceError(operation, 'ConflictException', `Schedule ${name} already exists.`)
                }
                if (
                    flags.get('action-after-completion') !== 'DELETE' ||
                    flags.get('schedule-expression-timezone') !== 'UTC'
                ) {
                    throw new Error(`the fake cloud models only one-time UTC schedules that delete themselves`)
                }
                this.schedules.set(name, {
                    expression: flags.get('schedule-expression')!,
                    target: parseJSON(flags.get('target')!) as Schedule['target'],
                })
                return { ScheduleArn: `arn:aws:scheduler:us-east-1:${this.account}:schedule/default/${name}` }
            }
            case 'scheduler get-schedule': {
                const schedule = this.schedules.get(flags.get('name')!)
                if (!schedule) {
                    throw serviceError(
                        operation,
                        'ResourceNotFoundException',
                        `Schedule ${flags.get('name')} does not exist.`
                    )
                }
                return {
                    Name: flags.get('name'),
                    ScheduleExpression: schedule.expression,
                    ScheduleExpressionTimezone: 'UTC',
                    ActionAfterCompletion: 'DELETE',
                    Target: schedule.target,
                }
            }
            case 'scheduler delete-schedule':
                if (!this.schedules.delete(flags.get('name')!)) {
                    throw serviceError(
                        operation,
                        'ResourceNotFoundException',
                        `Schedule ${flags.get('name')} does not exist.`
                    )
                }
                return null
            default:
                throw new Error(`the fake cloud does not model aws ${service} ${operation}`)
        }
    }
}
