import { execFile } from 'child_process'
import { chmodSync, mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { Client } from 'pg'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'

import { Aws, awsCli } from './aws'
import { Pooler, loadCloudProfile } from './profile'

export const READY_TIMEOUT_MS = 2 * 60_000
const RETRY_MS = 1_000
const PHASE_TIMEOUT_MS = 5_000
const LOG_LINES = 50
const FIRST_PORT = 6432
const DATABASE = 'cyclotron_node'
const CONFIG_DIR = '/etc/scenario-pooler'
const ECR_REGISTRY = /^\d{12}\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com$/

export type Target = { port: number; user: string; password: string; database: string }

export type PoolerHost = {
    aws: Aws
    docker(args: string[], input?: string): Promise<string>
    select1(target: Target): Promise<void>
    now(): number
    sleep(ms: number): Promise<void>
    log(line: string): void
    warn(line: string): void
}

const Cluster = z.object({
    Endpoint: z.string().min(1),
    Port: z.number().int().positive(),
    MasterUserSecret: z.object({ SecretArn: z.string().min(1) }),
})

const Credentials = z.object({ username: z.string().min(1), password: z.string().min(1) })

type Credentials = z.infer<typeof Credentials>

const quoted = (value: string): string => `"${value.replaceAll('"', '""')}"`

function configOf(pooler: Pooler, cluster: z.infer<typeof Cluster>, port: number): string {
    return [
        '[databases]',
        `${DATABASE} = host=${cluster.Endpoint} port=${cluster.Port} dbname=${DATABASE}`,
        '',
        '[pgbouncer]',
        ...Object.entries(pooler.settings).map(([key, value]) => `${key} = ${value}`),
        'listen_addr = 127.0.0.1',
        `listen_port = ${port}`,
        'auth_type = scram-sha-256',
        `auth_file = ${CONFIG_DIR}/userlist.txt`,
        'server_tls_sslmode = require',
        '',
    ].join('\n')
}

function writeReadable(file: string, content: string): void {
    writeFileSync(file, content)
    chmodSync(file, 0o644)
}

async function pullImage(host: PoolerHost, image: string): Promise<void> {
    const registry = image.split('/')[0]
    const region = ECR_REGISTRY.exec(registry)?.[1]
    if (region) {
        const token = await host.aws.text(['ecr', 'get-login-password', '--region', region])
        await host.docker(['login', '--username', 'AWS', '--password-stdin', registry], token)
    }
    await host.docker(['pull', image])
}

async function awaitAnswer(host: PoolerHost, target: Target, deadline: number): Promise<void> {
    for (;;) {
        try {
            return await host.select1(target)
        } catch (error) {
            if (host.now() >= deadline) {
                throw error
            }
            await host.sleep(RETRY_MS)
        }
    }
}

async function readCluster(host: PoolerHost, runId: string): Promise<[z.infer<typeof Cluster>, Credentials]> {
    const cluster = Cluster.parse(
        await host.aws.call([
            'rds',
            'describe-db-clusters',
            '--db-cluster-identifier',
            `scn-${runId}`,
            '--query',
            'DBClusters[0]',
        ])
    )
    const secret = await host.aws.text([
        'secretsmanager',
        'get-secret-value',
        '--secret-id',
        cluster.MasterUserSecret.SecretArn,
        '--query',
        'SecretString',
        '--output',
        'text',
    ])
    return [cluster, Credentials.parse(parseJSON(secret))]
}

export async function startPoolers(host: PoolerHost, pooler: Pooler, runId: string, root: string): Promise<number[]> {
    const [cluster, { username, password }] = await readCluster(host, runId)
    await pullImage(host, pooler.image)
    const configs = path.join(root, 'pooler')
    mkdirSync(configs, { recursive: true })
    chmodSync(configs, 0o700)
    const ports = Array.from({ length: pooler.replicas }, (_, replica) => FIRST_PORT + replica)
    for (const [replica, port] of ports.entries()) {
        const dir = path.join(configs, String(replica))
        mkdirSync(dir, { recursive: true })
        chmodSync(dir, 0o755)
        writeReadable(path.join(dir, 'pgbouncer.ini'), configOf(pooler, cluster, port))
        writeReadable(path.join(dir, 'userlist.txt'), `${quoted(username)} ${quoted(password)}\n`)
        await host.docker([
            'run',
            '-d',
            '--name',
            `scenario-pooler-${replica}`,
            '--network',
            'host',
            '--restart',
            'unless-stopped',
            '-v',
            `${dir}:${CONFIG_DIR}:ro`,
            '--entrypoint',
            'pgbouncer',
            pooler.image,
            `${CONFIG_DIR}/pgbouncer.ini`,
        ])
    }
    const deadline = host.now() + READY_TIMEOUT_MS
    for (const [replica, port] of ports.entries()) {
        try {
            await awaitAnswer(host, { port, user: username, password, database: DATABASE }, deadline)
        } catch (error) {
            const logs = await host
                .docker(['logs', '--tail', String(LOG_LINES), `scenario-pooler-${replica}`])
                .catch((logsError: Error) => logsError.message)
            throw new Error(
                `Pooler replica ${replica} on port ${port} did not answer SELECT 1 within ${READY_TIMEOUT_MS / 1000} s: ${(error as Error).message}\nIts last log lines:\n${logs}`
            )
        }
    }
    return ports
}

export async function main(args: string[], env: NodeJS.ProcessEnv, host: PoolerHost): Promise<number> {
    const [file] = args
    const runId = env.SCENARIO_RUN_ID
    if (!file || !runId) {
        host.warn('Usage: SCENARIO_RUN_ID=<run id> host-pooler.ts <cloud-profile.yaml>')
        return 1
    }
    try {
        const { pooler } = loadCloudProfile(file)
        const ports = await startPoolers(host, pooler, runId, env.SCENARIO_HOST_ROOT ?? '/opt/scenario')
        host.log(`Poolers answer SELECT 1 on ports ${ports.join(', ')}`)
        return 0
    } catch (error) {
        host.warn((error as Error).message)
        return 1
    }
}

export async function select1({ port, user, password, database }: Target): Promise<void> {
    const client = new Client({
        host: '127.0.0.1',
        port,
        user,
        password,
        database,
        connectionTimeoutMillis: PHASE_TIMEOUT_MS,
        query_timeout: PHASE_TIMEOUT_MS,
    })
    await client.connect()
    try {
        await client.query('SELECT 1')
    } finally {
        await client.end()
    }
}

function dockerCli(args: string[], input = ''): Promise<string> {
    return new Promise((resolve, reject) => {
        const child = execFile('docker', args, (error, stdout, stderr) =>
            error
                ? reject(new Error(`docker ${args[0]} failed: ${stderr.trim() || error.message}`))
                : resolve(`${stdout}${stderr}`)
        )
        child.stdin?.end(input)
    })
}

if (require.main === module) {
    const host: PoolerHost = {
        aws: awsCli(process.env),
        docker: dockerCli,
        select1,
        now: Date.now,
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
        log: (line) => process.stdout.write(`${line}\n`),
        warn: (line) => process.stderr.write(`${line}\n`),
    }
    void main(process.argv.slice(2), process.env, host).then((code) => process.exit(code))
}
