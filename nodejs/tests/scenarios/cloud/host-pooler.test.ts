import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

import { Aws, AwsError } from './aws'
import { PoolerHost, READY_TIMEOUT_MS, main, select1 } from './host-pooler'

const RUN_ID = '00000000-0000-4000-8000-000000000001'
const ENDPOINT = 'scn.cluster.example.com'
const SECRET_ARN = 'arn:aws:secretsmanager:us-east-1:000000000000:secret:rds-test'
const USER = 'scn admin'
const PASSWORD = 'p"ss w%rd'
const ECR_TOKEN = 'ecr-token'
const DIGEST = `sha256:${'b'.repeat(64)}`
const PUBLIC_IMAGE = `registry.example.com/pgbouncer@${DIGEST}`
const ECR_REGISTRY = '000000000000.dkr.ecr.us-east-1.amazonaws.com'
const ECR_IMAGE = `${ECR_REGISTRY}/pgbouncer@${DIGEST}`

type Ini = Record<string, Record<string, string>>

function parseIni(text: string): Ini {
    const ini: Ini = {}
    let section = ''
    for (const line of text.split('\n').map((raw) => raw.trim())) {
        const header = /^\[(.+)\]$/.exec(line)
        const entry = /^([^=;#]+?)\s*=\s*(.*)$/.exec(line)
        if (header) {
            section = header[1]
            ini[section] ??= {}
        } else if (entry) {
            if (entry[1] in ini[section]) {
                throw new Error(`pgbouncer: duplicate ${entry[1]}`)
            }
            ini[section][entry[1]] = entry[2]
        } else if (line !== '' && !/^[;#]/.test(line)) {
            throw new Error(`pgbouncer: syntax error in "${line}"`)
        }
    }
    return ini
}

function parseUserlist(text: string): Map<string, string> {
    const users = new Map<string, string>()
    for (const line of text.split('\n').filter((raw) => raw.trim() !== '')) {
        const entry = /^"((?:[^"]|"")*)"\s+"((?:[^"]|"")*)"$/.exec(line.trim())
        if (!entry) {
            throw new Error(`pgbouncer: broken auth file line ${line}`)
        }
        users.set(entry[1].replaceAll('""', '"'), entry[2].replaceAll('""', '"'))
    }
    return users
}

type Container = { name: string; image: string; flags: Map<string, string[]>; args: string[] }

type Pgbouncer = {
    container: Container
    settings: Record<string, string>
    databases: Record<string, string>
    users: Map<string, string>
}

class FakeHost implements PoolerHost {
    elapsed = 0
    containers: Container[] = []
    loggedIn = new Set<string>()
    pulled = new Set<string>()
    startsAfter = new Map<number, number>()
    out: string[] = []
    err: string[] = []

    aws: Aws = {
        call: (args) => {
            if (
                args.join(' ') ===
                `rds describe-db-clusters --db-cluster-identifier scn-${RUN_ID} --query DBClusters[0]`
            ) {
                return Promise.resolve({ Endpoint: ENDPOINT, Port: 5432, MasterUserSecret: { SecretArn: SECRET_ARN } })
            }
            return Promise.reject(new AwsError(args, 254, 'An error occurred (DBClusterNotFoundFault)'))
        },
        text: (args) => {
            const command = args.join(' ')
            if (
                command ===
                `secretsmanager get-secret-value --secret-id ${SECRET_ARN} --query SecretString --output text`
            ) {
                return Promise.resolve(JSON.stringify({ username: USER, password: PASSWORD }))
            }
            if (command === 'ecr get-login-password --region us-east-1') {
                return Promise.resolve(ECR_TOKEN)
            }
            return Promise.reject(new AwsError(args, 252, `unexpected ${command}`))
        },
    }

    docker = (args: string[], input?: string): Promise<void> => {
        const [command, ...rest] = args
        if (command === 'login') {
            const registry = rest[rest.length - 1]
            if (rest.join(' ') !== `--username AWS --password-stdin ${registry}` || input !== ECR_TOKEN) {
                return Promise.reject(new Error('docker login: unauthorized'))
            }
            this.loggedIn.add(registry)
            return Promise.resolve()
        }
        if (command === 'pull') {
            const registry = rest[0].split('/')[0]
            if (registry.endsWith('.amazonaws.com') && !this.loggedIn.has(registry)) {
                return Promise.reject(new Error('docker pull: no basic auth credentials'))
            }
            this.pulled.add(rest[0])
            return Promise.resolve()
        }
        if (command === 'run') {
            const flags = new Map<string, string[]>()
            let index = 0
            for (; rest[index]?.startsWith('-'); index++) {
                const flag = rest[index]
                const value = flag === '-d' ? '' : rest[++index]
                flags.set(flag, [...(flags.get(flag) ?? []), value])
            }
            const image = rest[index]
            if (!this.pulled.has(image)) {
                return Promise.reject(new Error(`docker run: ${image} not found`))
            }
            this.containers.push({ name: flags.get('--name')![0], image, flags, args: rest.slice(index + 1) })
            return Promise.resolve()
        }
        return Promise.reject(new Error(`docker ${command}: unexpected`))
    }

    select1 = ({
        port,
        user,
        password,
        database,
    }: {
        port: number
        user: string
        password: string
        database: string
    }): Promise<void> => {
        const pooler = this.poolers().find(({ settings }) => settings.listen_port === String(port))
        const waits = this.startsAfter.get(port) ?? 0
        if (!pooler || waits > 0) {
            this.startsAfter.set(port, waits - 1)
            return Promise.reject(new Error(`connect ECONNREFUSED 127.0.0.1:${port}`))
        }
        if (pooler.users.get(user) !== password) {
            return Promise.reject(new Error(`password authentication failed for user "${user}"`))
        }
        if (pooler.databases[database] !== `host=${ENDPOINT} port=5432 dbname=cyclotron_node`) {
            return Promise.reject(new Error(`no such database: ${database}`))
        }
        if (pooler.settings.server_tls_sslmode !== 'require' || pooler.users.get(USER) !== PASSWORD) {
            return Promise.reject(new Error('server login failed'))
        }
        return Promise.resolve()
    }

    now = (): number => this.elapsed

    sleep = (ms: number): Promise<void> => {
        this.elapsed += ms
        return Promise.resolve()
    }

    log = (line: string): void => {
        this.out.push(line)
    }

    warn = (line: string): void => {
        this.err.push(line)
    }

    poolers(): Pgbouncer[] {
        return this.containers.flatMap((container) => {
            const [mount] = container.flags.get('-v') ?? []
            const [hostDir, target, mode] = mount?.split(':') ?? []
            const onHost = (file: string): string => path.join(hostDir, path.relative(target, file))
            if (
                container.flags.get('--entrypoint')?.[0] !== 'pgbouncer' ||
                container.flags.get('--network')?.[0] !== 'host' ||
                mode !== 'ro' ||
                container.args.length !== 1
            ) {
                return []
            }
            const ini = parseIni(readFileSync(onHost(container.args[0]), 'utf8'))
            const settings = ini.pgbouncer
            if (settings.listen_addr !== '127.0.0.1') {
                return []
            }
            const users = parseUserlist(readFileSync(onHost(settings.auth_file), 'utf8'))
            return [{ container, settings, databases: ini.databases, users }]
        })
    }
}

describe('host-pooler', () => {
    let dir: string
    let host: FakeHost

    function poolOnHost(image: string, replicas = 2): Promise<number> {
        const profile = path.join(dir, 'cloud-profile.yaml')
        writeFileSync(
            profile,
            stringify({ pooler: { image, replicas, settings: { pool_mode: 'transaction', default_pool_size: 20 } } })
        )
        return main([profile], { SCENARIO_RUN_ID: RUN_ID, SCENARIO_HOST_ROOT: dir }, host)
    }

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-pooler-'))
        host = new FakeHost()
    })

    afterEach(() => rmSync(dir, { recursive: true, force: true }))

    it.each([
        ['a public registry', PUBLIC_IMAGE],
        ['a private ECR registry', ECR_IMAGE],
    ])('starts every replica from %s with the profile settings, in front of the run cluster', async (_, image) => {
        host.startsAfter.set(6433, 3)

        await expect(poolOnHost(image)).resolves.toBe(0)

        const poolers = host.poolers()
        expect(poolers.map(({ settings }) => settings.listen_port)).toEqual(['6432', '6433'])
        expect(new Set(poolers.map(({ container }) => container.name)).size).toBe(2)
        for (const { container, settings } of poolers) {
            expect(container.image).toBe(image)
            expect(container.flags.get('--restart')).toEqual(['unless-stopped'])
            expect(settings).toMatchObject({ pool_mode: 'transaction', default_pool_size: '20' })
        }
        expect(statSync(path.join(dir, 'pooler')).mode & 0o077).toBe(0)
    })

    it('fails naming the replica that never answers, once the readiness deadline passes', async () => {
        host.startsAfter.set(6433, Infinity)

        await expect(poolOnHost(PUBLIC_IMAGE)).resolves.toBe(1)

        expect(host.err.join('\n')).toMatch(/replica 1 on port 6433 .*ECONNREFUSED/)
        expect(host.elapsed).toBeGreaterThanOrEqual(READY_TIMEOUT_MS)
        expect(host.elapsed).toBeLessThan(READY_TIMEOUT_MS + 10_000)
    })

    it('fails without starting a pooler when the run cluster cannot be found', async () => {
        const profile = path.join(dir, 'cloud-profile.yaml')
        writeFileSync(profile, stringify({ pooler: { image: PUBLIC_IMAGE, replicas: 1, settings: {} } }))

        await expect(
            main([profile], { SCENARIO_RUN_ID: '00000000-0000-4000-8000-000000000009', SCENARIO_HOST_ROOT: dir }, host)
        ).resolves.toBe(1)

        expect(host.err.join('\n')).toContain('DBClusterNotFoundFault')
        expect(host.containers).toEqual([])
    })
})

describe('select1', () => {
    it.each([
        ['answers', 'posthog', true],
        ['rejects a wrong password', 'not-the-password', false],
    ])('%s through a real Postgres', async (_, password, answers) => {
        const answer = select1({ port: 5432, user: 'posthog', password, database: 'test_posthog' })

        await (answers ? expect(answer).resolves.toBeUndefined() : expect(answer).rejects.toThrow('password'))
    })
})
