import { execFile, spawn } from 'child_process'
import { closeSync, openSync, readFileSync, writeFileSync } from 'fs'
import Redis from 'ioredis'
import { Producer } from 'node-rdkafka'
import path from 'path'
import { Client, DatabaseError } from 'pg'
import { setTimeout as sleep } from 'timers/promises'
import { promisify } from 'util'
import { parse, stringify } from 'yaml'

import { getDefaultConfig, overrideWithEnv } from '~/common/config/config'
import { internalFetch } from '~/common/utils/request'
import { TEST_IDS_BELOW } from '~/tests/helpers/sql'
import { PluginsServerConfig } from '~/types'

import { signal as sendSignal } from './processes'
import { ConsumerGroup, ROLE_PORTS, RoleSpec, SCENARIO_SESSION_PREFIX, SES_RATE_LIMITER_VALKEY } from './roles'

export const PROBE_TIMEOUT_MS = 2000

export const SES_RATE_LIMIT_KEY = '@posthog/ses/global'

export const STACK = {
    postgresUrl: 'postgres://posthog:posthog@localhost:5432/posthog',
    cyclotronNodeUrl: 'postgres://posthog:posthog@localhost:5432/cyclotron_node',
    kafkaHosts: 'kafka:9092',
    redis: { host: '127.0.0.1', port: 6379 },
    sesRateLimiterValkey: SES_RATE_LIMITER_VALKEY,
    personhogReadinessUrl: 'http://127.0.0.1:9101/_readiness',
    kafkaContainer: 'posthog-kafka-1',
    composeProject: 'posthog',
    templates: ['template-email', 'template-webhook'],
}

export type Hogli = { command: string; cwd: string }

const HOGLI_STOP_GRACE_MS = 5000

async function hogliExit(
    hogli: Hogli,
    args: string[],
    logFile: string,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal
): Promise<number | null> {
    signal.throwIfAborted()
    const log = openSync(logFile, 'a')
    const child = spawn(hogli.command, args, { cwd: hogli.cwd, env, stdio: ['ignore', log, log], detached: true })
    closeSync(log)
    const stopGroup = (sig: NodeJS.Signals): void => {
        if (child.pid !== undefined) {
            sendSignal(-child.pid, sig)
        }
    }
    let kill: NodeJS.Timeout | undefined
    const abort = (): void => {
        stopGroup('SIGTERM')
        kill = setTimeout(() => stopGroup('SIGKILL'), HOGLI_STOP_GRACE_MS)
    }
    signal.addEventListener('abort', abort, { once: true })
    try {
        const code = await new Promise<number | null>((resolve, reject) => {
            child.once('error', reject)
            child.once('exit', resolve)
        })
        if (signal.aborted) {
            stopGroup('SIGKILL')
            signal.throwIfAborted()
        }
        return code
    } finally {
        signal.removeEventListener('abort', abort)
        clearTimeout(kill)
    }
}

async function runHogli(
    hogli: Hogli,
    args: string[],
    logFile: string,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal
): Promise<void> {
    const code = await hogliExit(hogli, args, logFile, env, signal)
    if (code !== 0) {
        throw new Error(`hogli ${args.join(' ')} exited with ${code}; see ${logFile}`)
    }
}

const NOT_REACHABLE = 3
export const FIRST_START_TIMEOUT_S = 3600

const STACK_UNITS = {
    intents: ['product_analytics', 'workflows'],
    exclude_units: ['nodejs', 'frontend', 'ingestion', 'ngrok'],
}

const COMPOSE_BASE = String.raw`docker compose -p (?<project>[\w.-]+) -f docker-compose\.dev\.yml -f docker-compose\.profiles\.yml(?: --profile [\w-]+)*`
const ECHO = String.raw`echo "[^"$\x60\\]*"`
const GENERATED_COMPOSE_SHELL = new RegExp(
    String.raw`^(?<head>(?:echo '[^']*' && )?if \[ "\$\{POSTHOG_SANDBOX:-\}" = "1" \]; then ${ECHO} && echo "docker-compose ready" && sleep infinity; else (?<compose>${COMPOSE_BASE}))` +
        String.raw` up --pull always -d ` +
        String.raw`(?<tail>\|\| \{ ${ECHO}; exit 1; \} && echo "docker-compose ready" && \k<compose> logs --tail=100 -f; fi)$`
)
const KEEPING_COMPOSE_UP = ' up --pull always --no-recreate -d '

export class StackNotReadyError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'StackNotReadyError'
    }
}

// The keys hogli writes on its docker-compose proc. Any other, such as a cmd that phrocs would run in place of the
// shell or a merge key that brings one in, is refused rather than interpreted.
const COMPOSE_PROC_KEYS = new Set(['shell', 'ready_pattern', 'capability', 'groups', 'autostart'])

export function keepRunningContainers(mprocsYaml: string): { yaml: string; project: string } {
    let config: { procs?: Record<string, Record<string, unknown> | null> } | null
    try {
        config = parse(mprocsYaml)
    } catch (error) {
        throw new StackNotReadyError(`The dev config hogli generated is not valid YAML: ${(error as Error).message}`)
    }
    const compose = config?.procs?.['docker-compose']
    const shell = typeof compose?.shell === 'string' ? compose.shell : ''
    const otherKeys = Object.keys(compose ?? {}).filter((key) => !COMPOSE_PROC_KEYS.has(key))
    const generated = otherKeys.length === 0 ? GENERATED_COMPOSE_SHELL.exec(shell) : null
    if (!compose || !generated) {
        throw new StackNotReadyError(
            `The dev config hogli generated has no docker-compose proc in the shape the runner knows, one \`docker compose up --pull always -d\` then its logs, so the runner cannot keep the running containers. Its shell is: ${shell || 'missing'}${otherKeys.length > 0 ? `; its other keys: ${otherKeys.join(', ')}` : ''}`
        )
    }
    compose.shell = generated.groups!.head + KEEPING_COMPOSE_UP + generated.groups!.tail
    return { yaml: stringify(config, { lineWidth: 0 }), project: generated.groups!.project }
}

// bin/start moves these services' data from anonymous to named volumes before compose runs, and expects compose
// to recreate the containers on the named ones. A kept container would go on writing to its old volume.
const NAMED_VOLUMES: Record<string, string> = { clickhouse: 'clickhouse-data', zookeeper: 'zookeeper-data' }

export async function onAnonymousVolumes(
    docker: string,
    project: string,
    services: string[],
    signal?: AbortSignal
): Promise<string[]> {
    const moving = services.filter((service) => service in NAMED_VOLUMES)
    if (moving.length === 0) {
        return []
    }
    const { stdout } = await promisify(execFile)(docker, ['volume', 'ls', '--format', '{{.Name}}'], {
        timeout: 10_000,
        signal,
    })
    const volumes = new Set(stdout.split('\n'))
    return moving.filter((service) => !volumes.has(`${project}_${NAMED_VOLUMES[service]}`))
}

export type ExistingServices = { running: string[]; stopped: string[]; containers: string[] }

// A one-shot service such as kafka-init has restart policy "no" and exits 0 when it is done. Any other container
// that is not running would start again as it is, with the mounts of the worktree that made it.
export async function existingServices(
    docker: string,
    project: string,
    signal?: AbortSignal
): Promise<ExistingServices> {
    const run = async (args: string[]): Promise<string[][]> => {
        const { stdout } = await promisify(execFile)(docker, args, { timeout: 10_000, signal })
        return stdout
            .split('\n')
            .filter((line) => line !== '')
            .map((line) => line.split(' '))
    }
    const listed = await run([
        'ps',
        '--all',
        '--filter',
        `label=com.docker.compose.project=${project}`,
        '--filter',
        'label=com.docker.compose.oneoff=False',
        '--format',
        '{{.ID}} {{.Label "com.docker.compose.service"}} {{.State}}',
    ])
    const notRunning = listed.filter(([, , state]) => state !== 'running').map(([id]) => id)
    const finished =
        notRunning.length === 0
            ? []
            : await run([
                  'inspect',
                  '--format',
                  '{{.Id}} {{.HostConfig.RestartPolicy.Name}} {{.State.Status}} {{.State.ExitCode}}',
                  ...notRunning,
              ])
    const done = new Set(
        finished
            .filter(([, policy, status, code]) => policy === 'no' && status === 'exited' && code === '0')
            .map(([id]) => id)
    )
    const stopped = new Set(
        listed
            .filter(([id, , state]) => state !== 'running' && ![...done].some((full) => full.startsWith(id)))
            .map(([, service]) => service)
    )
    const running = new Set(listed.filter(([, , state]) => state === 'running').map(([, service]) => service))
    return {
        running: [...running].filter((service) => !stopped.has(service)).sort(),
        stopped: [...stopped].sort(),
        containers: listed.filter(([, service]) => running.has(service) && !stopped.has(service)).map(([id]) => id),
    }
}

export type ContainerStart = { service: string; finishedJob: boolean; startedAt: string }

// A kept container that stops after the check above is started again by compose as it is, with the mounts of the
// worktree that made it. Its start time shows that.
export async function containerStarts(
    docker: string,
    containers: string[],
    signal?: AbortSignal
): Promise<Map<string, ContainerStart>> {
    if (containers.length === 0) {
        return new Map()
    }
    const format =
        '{{.Id}} {{index .Config.Labels "com.docker.compose.service"}} {{.HostConfig.RestartPolicy.Name}} {{.State.Status}} {{.State.ExitCode}} {{.State.StartedAt}}'
    // docker inspect prints the containers it finds, and exits 1 with "No such object" for each one that is gone.
    const stdout = await promisify(execFile)(docker, ['inspect', '--format', format, ...containers], {
        timeout: 10_000,
        signal,
    }).then(
        (result) => result.stdout,
        (error: Error & { code?: unknown; stdout?: string; stderr?: string }) => {
            const errors = (error.stderr ?? '').split('\n').filter((line) => line !== '')
            const gone =
                errors.length > 0 &&
                errors.every((line) => {
                    const missing = /^Error(?: response from daemon)?: No such (?:object|container): (\S+)$/.exec(line)
                    return missing !== null && containers.includes(missing[1])
                })
            if (error.code !== 1 || signal?.aborted || !gone) {
                throw error
            }
            return error.stdout ?? ''
        }
    )
    const lines = stdout.split('\n').filter((line) => line !== '')
    return new Map(
        lines.map((line) => {
            const [id, service, policy, status, code, startedAt] = line.split(' ')
            return [id, { service, finishedJob: policy === 'no' && status === 'exited' && code === '0', startedAt }]
        })
    )
}

function startedAgain(project: string, services: string[]): StackNotReadyError {
    return new StackNotReadyError(
        `The dev services ${[...new Set(services)].sort().join(', ')} started again while the runner started the stack, so they may run with the mounts of the worktree that made them. Recreate them from your worktree with \`docker compose -p ${project} -f docker-compose.dev.yml -f docker-compose.profiles.yml up -d --no-deps --force-recreate <service>\`, then run again.`
    )
}

export async function startStack(
    hogli: Hogli,
    docker: string,
    stateDir: string,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal
): Promise<void> {
    const config = path.join(stateDir, 'mprocs.yaml')
    const logFile = path.join(stateDir, 'hogli.log')
    const hogliEnv = { ...env, HOGLI_MPROCS_PATH: config, HOGLI_SKIP_ZOMBIE_CHECK: '1' }
    const waited = await hogliExit(hogli, ['wait'], logFile, hogliEnv, signal)
    if (waited === 0) {
        return
    }
    if (waited !== NOT_REACHABLE) {
        throw new Error(`hogli wait exited with ${waited}; see ${logFile}`)
    }
    writeFileSync(config, JSON.stringify({ _posthog: STACK_UNITS }))
    await runHogli(hogli, ['dev:generate'], logFile, hogliEnv, signal)
    const { yaml, project } = keepRunningContainers(readFileSync(config, 'utf8'))
    writeFileSync(config, yaml)
    const { running: kept, stopped, containers } = await existingServices(docker, project, signal)
    if (stopped.length > 0) {
        throw new StackNotReadyError(
            `The dev services ${stopped.join(', ')} have containers that are not running and are not finished one-shot jobs. The runner keeps only running services, because a stopped container starts again with the mounts of the worktree that made it and the volumes it had. Recreate them from your worktree with \`docker compose -p ${project} -f docker-compose.dev.yml -f docker-compose.profiles.yml up -d --no-deps --force-recreate <service>\`, or start the stack with \`hogli start\` while no other worktree uses it, then run again.`
        )
    }
    const unmoved = await onAnonymousVolumes(docker, project, kept, signal)
    if (unmoved.length > 0) {
        throw new StackNotReadyError(
            `The dev services ${unmoved.join(', ')} still keep their data on anonymous volumes, and the runner would keep them there. Start the stack once with \`hogli start\` while no other worktree uses it, so it moves the data to named volumes, then run again.`
        )
    }
    if (kept.length > 0) {
        process.stderr.write(
            `Keeping the existing dev services as they are: ${kept.join(', ')}. A change to their compose definition is not applied until they are recreated.\n`
        )
    }
    const before = await containerStarts(docker, containers, signal)
    await runHogli(hogli, ['up', '-d', '--custom', config], logFile, hogliEnv, signal)
    await runHogli(hogli, ['wait', '--timeout', String(FIRST_START_TIMEOUT_S)], logFile, hogliEnv, signal)
    const after = await containerStarts(docker, [...before.keys()], signal)
    const again = [...before].filter(([id, start]) => {
        const now = after.get(id)
        return now !== undefined && now.startedAt !== start.startedAt && !now.finishedJob
    })
    if (again.length > 0) {
        throw startedAgain(
            project,
            again.map(([, { service }]) => service)
        )
    }
}

export type MigratedTable = { url: string; table: string }

export async function untilMigrated(
    tables: MigratedTable[],
    withinMs: number,
    intervalMs: number,
    signal: AbortSignal,
    pause = (ms: number): Promise<void> => sleep(ms, undefined, { signal })
): Promise<void> {
    const deadline = performance.now() + withinMs
    for (;;) {
        signal.throwIfAborted()
        const missing = await Promise.all(
            tables.map(({ url, table }) =>
                withPostgres(async (client) => {
                    const { rows } = await client.query<{ present: boolean }>(
                        'SELECT to_regclass($1) IS NOT NULL AS present',
                        [table]
                    )
                    return rows[0].present ? null : `${new URL(url).pathname.slice(1)} has no table ${table}`
                }, url).catch((error: Error) => error.message)
            )
        )
        signal.throwIfAborted()
        const problems = missing.filter((problem): problem is string => problem !== null)
        if (problems.length === 0) {
            return
        }
        if (performance.now() >= deadline) {
            throw new StackNotReadyError(
                `Postgres was not ready with its migrations within ${withinMs / 1000} seconds: ${problems.join('; ')}. Check \`docker ps\` for a restarted posthog-db-1 and the migrate procs in hogli's log.`
            )
        }
        await pause(Math.min(intervalMs, Math.max(0, deadline - performance.now())))
    }
}

export async function syncTemplates(
    hogli: Hogli,
    stateDir: string,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal
): Promise<void> {
    await runHogli(hogli, ['dev:sync-hog-templates'], path.join(stateDir, 'hogli.log'), env, signal)
}

export async function withPostgres<T>(
    run: (client: Client) => Promise<T>,
    connectionString = STACK.postgresUrl,
    statementTimeoutMs = PROBE_TIMEOUT_MS
): Promise<T> {
    const client = new Client({
        connectionString,
        connectionTimeoutMillis: PROBE_TIMEOUT_MS,
        query_timeout: statementTimeoutMs,
        statement_timeout: statementTimeoutMs,
    })
    // The server can end the connection between queries, as a failover or a terminated backend does. Without
    // a listener the client throws that from an event handler and takes the process down.
    client.on('error', () => undefined)
    try {
        await client.connect()
        return await run(client)
    } catch (error) {
        throw new Error(`Postgres at ${new URL(connectionString).host} failed: ${(error as Error).message}`, {
            cause: error,
        })
    } finally {
        await client.end().catch(() => undefined)
    }
}

export type ScratchSchema = { url: string; create(): Promise<void>; drop(): Promise<void> }

export function scratchSchema(connectionString: string, schema: string, tables: string[]): ScratchSchema {
    const searchPath = encodeURIComponent(`-c search_path=${schema}`)
    return {
        url: `${connectionString}${connectionString.includes('?') ? '&' : '?'}options=${searchPath}`,
        create: () =>
            withPostgres(async (client) => {
                await client.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`)
                await client.query(`CREATE SCHEMA ${schema}`)
                for (const table of tables) {
                    await client.query(`CREATE TABLE ${schema}.${table} (LIKE public.${table} INCLUDING ALL)`)
                }
                const { rows } = await client.query<{ type: string }>(
                    `SELECT DISTINCT t.typname AS type
                     FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
                     WHERE a.attrelid = ANY($1::regclass[]) AND t.typtype = 'e'
                       AND t.typnamespace = 'public'::regnamespace`,
                    [tables.map((table) => `public.${table}`)]
                )
                for (const { type } of rows) {
                    await client.query(`CREATE DOMAIN ${schema}.${type} AS public.${type}`)
                }
            }, connectionString),
        drop: async () => {
            await withPostgres((client) => client.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`), connectionString)
        },
    }
}

export async function missingTemplates(postgresUrl: string): Promise<string[]> {
    const present = await withPostgres(async (client) => {
        const { rows } = await client.query<{ template_id: string }>(
            'SELECT DISTINCT template_id FROM posthog_hogfunctiontemplate WHERE template_id = ANY($1)',
            [STACK.templates]
        )
        return rows.map((row) => row.template_id)
    }, postgresUrl)
    return STACK.templates.filter((template) => !present.includes(template))
}

export function membersOf(rpkDescribe: string): number | null {
    const members = /^MEMBERS\s+(\d+)\s*$/m.exec(rpkDescribe)
    return members ? Number(members[1]) : null
}

export async function rpkOrThrow(docker: string, args: string[], signal?: AbortSignal): Promise<string> {
    const { stdout } = await promisify(execFile)(docker, ['exec', STACK.kafkaContainer, 'rpk', ...args], {
        timeout: 10_000,
        signal,
    })
    return stdout
}

export function rpk(docker: string, args: string[]): Promise<string> {
    return rpkOrThrow(docker, args).catch((error: unknown) => {
        const { stdout = '', stderr = '' } = error as { stdout?: string; stderr?: string }
        return `${stdout}${stderr}` || String(error)
    })
}

export async function groupMembers(group: string, docker: string): Promise<number> {
    const output = await rpk(docker, ['group', 'describe', group])
    const members = membersOf(output)
    if (members === null) {
        throw new Error(`Could not read the members of ${group} from rpk:\n${output}`)
    }
    return members
}

const groupOrPartitionErrored = (rpkDescribe: string): boolean =>
    /^ERROR\s/m.test(rpkDescribe) || /^TOPIC\s.*\sERROR\s*$/m.test(rpkDescribe)

export function lagOf(rpkDescribe: string): number | null {
    if (groupOrPartitionErrored(rpkDescribe)) {
        return null
    }
    const lag = /^TOTAL-LAG\s+(\d+)\s*$/m.exec(rpkDescribe)
    return lag ? Number(lag[1]) : null
}

export async function groupLag(group: string, docker: string): Promise<number> {
    const output = await rpkOrThrow(docker, ['group', 'describe', group])
    const lag = lagOf(output)
    if (lag === null) {
        throw new Error(`Could not read the lag of ${group} from rpk:\n${output}`)
    }
    return lag
}

export function seekFailures(rpkSeek: string): string[] {
    const lines = rpkSeek.split('\n').filter((line) => line.trim() !== '')
    const header = lines[0] ?? ''
    if (/UNKNOWN_TOPIC_OR_PARTITION/.test(header)) {
        return []
    }
    if (!/^TOPIC\s+PARTITION\s/.test(header)) {
        return [rpkSeek.trim() || 'rpk printed nothing']
    }
    const errorAt = header.indexOf('ERROR')
    if (errorAt < 0) {
        return []
    }
    return lines.slice(1).flatMap((row) => {
        const error = row.slice(errorAt).trim()
        const [topic, partition] = row.trim().split(/\s+/)
        return error ? [`${topic}/${partition}: ${error}`] : []
    })
}

const CREATED_OR_PRESENT = /^(OK|TOPIC_ALREADY_EXISTS\b)/

export function topicCreateFailures(rpkCreate: string): string[] {
    const [header = '', ...rows] = rpkCreate.split('\n').filter((line) => line.trim() !== '')
    if (!/^TOPIC\s+STATUS\s*$/.test(header)) {
        return [rpkCreate.trim() || 'rpk printed nothing']
    }
    return rows.flatMap((row) => {
        const [topic, ...words] = row.trim().split(/\s+/)
        const status = words.join(' ')
        return CREATED_OR_PRESENT.test(status) ? [] : [`${topic}: ${status}`]
    })
}

export async function createTopics(topics: string[], docker: string): Promise<void> {
    if (topics.length === 0) {
        return
    }
    const failures = topicCreateFailures(await rpk(docker, ['topic', 'create', '--', ...topics]))
    if (failures.length > 0) {
        throw new Error(`Could not create the Kafka topics the roles read:\n${failures.join('\n')}`)
    }
}

export async function seekToEnd({ group, topics }: ConsumerGroup, docker: string): Promise<void> {
    for (const topic of topics) {
        const output = await rpk(docker, [
            'group',
            'seek',
            group,
            '--to',
            'end',
            '--topics',
            topic,
            '--allow-new-topics',
        ])
        const failures = seekFailures(output)
        if (failures.length > 0) {
            throw new Error(`Could not move ${group} to the end of ${topic}:\n${failures.join('\n')}`)
        }
    }
}

export const cyclotronUrlOf = (spec: RoleSpec): string =>
    spec.cyclotronUrl ?? (spec.env.CYCLOTRON_NODE_DATABASE_URL || STACK.cyclotronNodeUrl)

export const writerUrlOf = (env: NodeJS.ProcessEnv, settings: Record<string, string> = {}): string | undefined =>
    env.SCENARIO_RUN_MANIFEST
        ? env.SCENARIO_WRITER_URL || undefined
        : env.SCENARIO_WRITER_URL ||
          settings.CYCLOTRON_NODE_DATABASE_URL ||
          env.CYCLOTRON_NODE_DATABASE_URL ||
          STACK.cyclotronNodeUrl

const settingsOf = (spec: RoleSpec): PluginsServerConfig =>
    overrideWithEnv({ ...getDefaultConfig(), DATABASE_URL: STACK.postgresUrl }, spec.env)

export const postgresUrlOf = (spec: RoleSpec): string => settingsOf(spec).DATABASE_URL

const LOOPBACK_HOSTS = ['localhost', '127.0.0.1', '[::1]']
const POSTGRES_URL = /^postgres(ql)?:\/\//

function serverOf(url: string): string {
    const { hostname, port } = new URL(url)
    return `${LOOPBACK_HOSTS.includes(hostname) ? 'localhost' : hostname}:${port || '5432'}`
}

export function postgresServersOf(spec: RoleSpec, postgresUrl: string): string[] {
    // A role that reaches Cyclotron through the edge's proxy still holds its sessions on the database behind it.
    const direct =
        spec.cyclotronUrl === undefined
            ? spec
            : { ...spec, env: { ...spec.env, CYCLOTRON_NODE_DATABASE_URL: spec.cyclotronUrl } }
    const urls = [
        postgresUrl,
        ...Object.values(settingsOf(direct)).filter(
            (value): value is string => typeof value === 'string' && POSTGRES_URL.test(value)
        ),
    ]
    return urls.filter((url, i) => urls.findIndex((other) => serverOf(other) === serverOf(url)) === i)
}

export const RESIDENT_TEAMS_FROM = TEST_IDS_BELOW

export async function deleteUnfinishedJobs(cyclotronUrl: string): Promise<void> {
    await withPostgres(
        (client) =>
            client.query("DELETE FROM cyclotron_jobs WHERE status IN ('available', 'running') AND team_id < $1", [
                RESIDENT_TEAMS_FROM,
            ]),
        cyclotronUrl
    )
}

export type Sessions = { names: string[]; prefix: string }

const ROLE_SESSIONS: Sessions = { names: Object.keys(ROLE_PORTS), prefix: SCENARIO_SESSION_PREFIX }

export async function terminateRoleConnections(
    postgresUrl: string,
    share: number,
    { names, prefix }: Sessions = ROLE_SESSIONS
): Promise<number> {
    return await withPostgres(async (client) => {
        const { rows } = await client.query<{ pid: number }>(
            `SELECT pid FROM pg_stat_activity
             WHERE pid <> pg_backend_pid() AND (application_name = ANY($1) OR starts_with(application_name, $2))
             ORDER BY random()`,
            [names, prefix]
        )
        const chosen = rows.slice(0, Math.ceil(share * rows.length)).map(({ pid }) => pid)
        const terminated = await client.query<{ terminated: number }>(
            'SELECT count(*) FILTER (WHERE pg_terminate_backend(pid))::int AS terminated FROM unnest($1::int[]) AS pid',
            [chosen]
        )
        return terminated.rows[0].terminated
    }, postgresUrl)
}

const DOCKER_READ_WITHIN_MS = 10_000

export async function serviceImagesOf(docker: string): Promise<string[]> {
    const run = (args: string[]): Promise<string> =>
        promisify(execFile)(docker, args, { timeout: DOCKER_READ_WITHIN_MS }).then(({ stdout }) => stdout)
    const containers = (await run(['ps', '-q', '--filter', `label=com.docker.compose.project=${STACK.composeProject}`]))
        .split('\n')
        .filter(Boolean)
    if (containers.length === 0) {
        return []
    }
    const format = '{{index .Config.Labels "com.docker.compose.service"}} {{.Config.Image}} {{.Image}}'
    return (await run(['inspect', '--format', format, ...containers])).split('\n').filter(Boolean).sort()
}

export async function rolesNotReady(specs: RoleSpec[]): Promise<RoleSpec[]> {
    const results = await Promise.all(
        specs.map((spec) =>
            expectOk(`http://127.0.0.1:${spec.port}/_health`).then(
                () => null,
                () => spec
            )
        )
    )
    return results.filter((spec): spec is RoleSpec => spec !== null)
}

export async function forgetSesBucket({ host, port }: { host: string; port: number }): Promise<void> {
    const valkey = new Redis({
        host,
        port,
        lazyConnect: true,
        commandTimeout: PROBE_TIMEOUT_MS,
        maxRetriesPerRequest: 0,
    })
    try {
        await valkey.connect()
        await valkey.del(SES_RATE_LIMIT_KEY)
    } finally {
        valkey.disconnect()
    }
}

export async function pingRedis({ host, port }: { host: string; port: number }): Promise<void> {
    const redis = new Redis({
        host,
        port,
        lazyConnect: true,
        connectTimeout: PROBE_TIMEOUT_MS,
        commandTimeout: PROBE_TIMEOUT_MS,
        enableReadyCheck: false,
        maxRetriesPerRequest: 0,
        enableOfflineQueue: false,
        retryStrategy: () => null,
    })
    try {
        await redis.connect()
        await redis.ping()
    } finally {
        redis.disconnect()
    }
}

async function pingKafka(): Promise<void> {
    const producer = new Producer({ 'metadata.broker.list': STACK.kafkaHosts })
    await new Promise<void>((resolve, reject) =>
        producer.connect({ timeout: PROBE_TIMEOUT_MS }, (error) => (error ? reject(error) : resolve()))
    )
    await new Promise((resolve) => producer.disconnect(resolve))
}

class HttpAnswer extends Error {}

export async function expectOk(url: string): Promise<void> {
    const { status } = await internalFetch(url, { timeoutMs: PROBE_TIMEOUT_MS })
    if (status !== 200) {
        throw new HttpAnswer(`${url} answered ${status}`)
    }
}

export type ProbeFailure = {
    name: string
    reason: string
    unanswered: boolean
    hostLimit?: string
    sockets?: Record<string, number>
}

export type Probes = Record<string, () => Promise<unknown>>

export function dependencyProbes(
    edgeUrl: string | undefined,
    postgresUrl: string,
    sesValkey: { host: string; port: number }
): Probes {
    return {
        postgres: () => withPostgres((client) => client.query('SELECT 1'), postgresUrl),
        kafka: pingKafka,
        redis: () => pingRedis(STACK.redis),
        'ses-rate-limiter-valkey': () => pingRedis(sesValkey),
        personhog: () => expectOk(STACK.personhogReadinessUrl),
        'provider-edge': () => (edgeUrl ? expectOk(`${edgeUrl}/_health`) : Promise.reject(new Error('not started'))),
    }
}

const ANSWER_CODES = new Set(['ECONNREFUSED', 'ECONNRESET', 'ENOTFOUND', 'EHOSTUNREACH'])

const HOST_LIMITS: Record<string, string> = {
    EADDRNOTAVAIL: 'local ports',
    EMFILE: 'file descriptors',
    ENFILE: 'file descriptors',
}

const TIMER_SLACK_MS = 10

const SOCKET_GROUPS_KEPT = 20

// A host out of local ports lists tens of thousands of sockets, which is past execFile's 1 MiB default.
const SOCKET_LISTING_MAX_BYTES = 64 * 1024 * 1024

// What held the host's ports is gone once the run ends, so the check keeps the busiest TCP states and peers.
async function socketsOf(): Promise<Record<string, number> | undefined> {
    try {
        const { stdout } = await promisify(execFile)('ss', ['-tanH'], {
            timeout: PROBE_TIMEOUT_MS,
            maxBuffer: SOCKET_LISTING_MAX_BYTES,
        })
        const counts = new Map<string, number>()
        for (const line of stdout.split('\n')) {
            const [state, , , , peer] = line.trim().split(/\s+/)
            if (peer !== undefined) {
                counts.set(`${state} ${peer}`, (counts.get(`${state} ${peer}`) ?? 0) + 1)
            }
        }
        return Object.fromEntries([...counts].sort(([, a], [, b]) => b - a).slice(0, SOCKET_GROUPS_KEPT))
    } catch {
        return undefined
    }
}

const codeOf = (error: unknown): unknown =>
    typeof error === 'object' && error !== null && 'code' in error ? error.code : undefined

const isTypedAnswer = (error: unknown): boolean =>
    error instanceof HttpAnswer || error instanceof DatabaseError || ANSWER_CODES.has(String(codeOf(error)))

const isAnswer = (error: unknown): boolean =>
    isTypedAnswer(error) || (error instanceof Error && isTypedAnswer(error.cause))

export const hostLimitOf = (error: unknown): string | undefined =>
    HOST_LIMITS[String(codeOf(error))] ??
    (error instanceof Error ? HOST_LIMITS[String(codeOf(error.cause))] : undefined)

export async function failedProbes(probes: Probes): Promise<ProbeFailure[]> {
    const results = await Promise.all(
        Object.entries(probes).map(async ([name, probe]): Promise<ProbeFailure | null> => {
            const startedAt = performance.now()
            try {
                await probe()
                return null
            } catch (error) {
                const ranOutItsClock = performance.now() - startedAt >= PROBE_TIMEOUT_MS - TIMER_SLACK_MS
                const reason = error instanceof Error ? error.message : String(error)
                const hostLimit = hostLimitOf(error)
                const sockets = hostLimit ? await socketsOf() : undefined
                return {
                    name,
                    reason,
                    unanswered: ranOutItsClock && !isAnswer(error),
                    ...(hostLimit ? { hostLimit } : {}),
                    ...(sockets ? { sockets } : {}),
                }
            }
        })
    )
    return results.filter((failure): failure is ProbeFailure => failure !== null)
}
