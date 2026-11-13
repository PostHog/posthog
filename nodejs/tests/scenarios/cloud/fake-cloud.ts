import { readFileSync, writeFileSync } from 'fs'

import { parseJSON } from '~/common/utils/json-parse'

import { Aws, AwsError } from './aws'

type Schedule = { expression: string; target: { Arn: string; RoleArn: string; Input: string } }

export type FakeCloudOptions = {
    now: () => Date
    account?: string
    expiration?: Date | null
    ssoSession?: string
    orderable?: string[]
    denied?: string[]
}

const ACTION_OF: Record<string, string> = {
    's3api list-objects-v2': 's3:ListBucket',
    'resourcegroupstaggingapi get-resources': 'tag:GetResources',
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
        if (args[i].startsWith('--')) {
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
    expiration: Date | null
    ssoSession: string | undefined
    readonly orderable: string[]
    readonly denied: Set<string>
    private readonly failures = new Map<string, number>()
    private readonly calls = new Map<string, number>()

    constructor(private readonly options: FakeCloudOptions) {
        this.account = options.account ?? '000000000000'
        this.expiration = options.expiration === undefined ? null : options.expiration
        this.ssoSession = options.ssoSession
        this.orderable = options.orderable ?? ['db.r8g.2xlarge', 'db.serverless']
        this.denied = new Set(options.denied ?? [])
    }

    failOnCall(operation: string, nth: number = 1): void {
        this.failures.set(operation, (this.calls.get(operation) ?? 0) + nth)
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

    private fireDueSchedules(): void {
        const now = this.options.now().getTime()
        for (const [name, schedule] of this.schedules) {
            if (atOf(schedule.expression) <= now) {
                const { StackName } = parseJSON(schedule.target.Input) as { StackName: string }
                this.deleteStackRequests.push({
                    stackName: StackName,
                    at: new Date(atOf(schedule.expression)).toISOString(),
                })
                this.schedules.delete(name)
            }
        }
    }

    private handle(args: string[]): unknown {
        this.fireDueSchedules()
        const [service, operation, ...rest] = args
        const { flags, positionals } = flagsOf(rest)
        const count = (this.calls.get(operation) ?? 0) + 1
        this.calls.set(operation, count)
        if (this.failures.get(operation) === count) {
            throw serviceError(operation, 'InternalFailure', 'injected by the fake cloud')
        }
        const action = actionOf(service, operation)
        if (this.denied.has(action)) {
            throw serviceError(operation, 'AccessDeniedException', `User is not authorized to perform: ${action}`)
        }
        return this.answer(service, operation, flags, positionals)
    }

    private answer(service: string, operation: string, flags: Map<string, string>, positionals: string[]): unknown {
        switch (`${service} ${operation}`) {
            case 'sts get-caller-identity':
                return {
                    Account: this.account,
                    Arn: `arn:aws:sts::${this.account}:assumed-role/developers/person`,
                    UserId: 'AROAEXAMPLE:person',
                }
            case 'configure get':
                if (this.ssoSession === undefined) {
                    throw new AwsError(['configure', 'get'], 1, '')
                }
                return this.ssoSession
            case 'configure export-credentials':
                return {
                    Version: 1,
                    AccessKeyId: 'ASIAEXAMPLE',
                    SecretAccessKey: 'example-secret',
                    SessionToken: 'example-token',
                    ...(this.expiration ? { Expiration: this.expiration.toISOString() } : {}),
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
            case 'cloudformation describe-stacks':
                throw serviceError(
                    operation,
                    'ValidationError',
                    `Stack with id ${flags.get('stack-name')} does not exist`
                )
            case 'ssm get-command-invocation':
                throw serviceError(operation, 'InvocationDoesNotExist', 'no such invocation')
            case 'cloudwatch get-metric-data':
                return { MetricDataResults: [] }
            case 'logs filter-log-events':
                return { events: [] }
            case 'resourcegroupstaggingapi get-resources':
                return { ResourceTagMappingList: [] }
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
