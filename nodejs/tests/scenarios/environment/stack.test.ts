import { parse } from 'yaml'

import { defaultConfig } from '~/common/config/config'

import { StackNotReadyError, keepRunningContainers, untilMigrated, withPostgres } from './stack'

const URL = defaultConfig.CYCLOTRON_NODE_DATABASE_URL!

const COMPOSE = 'docker compose -p posthog -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile temporal'

const SANDBOX =
    'if [ "${POSTHOG_SANDBOX:-}" = "1" ]; then echo "Sandbox" && echo "docker-compose ready" && sleep infinity; else '

const composeShell = (compose: string, up: string, between = ''): string =>
    `${SANDBOX}${compose} ${up} || { echo "docker compose up failed"; exit 1; } && echo "docker-compose ready" && ${between}${compose} logs --tail=100 -f; fi`

const generatedConfig = (shell: string): string =>
    `procs:\n  docker-compose:\n    shell: ${JSON.stringify(shell)}\n    ready_pattern: docker-compose ready\n  backend:\n    shell: bin/start-backend\n_posthog:\n  intents: [workflows]\n`

describe('withPostgres', () => {
    it('survives the server ending its connection between queries, as a failover does', async () => {
        const ended = withPostgres(async (client) => {
            const { rows } = await client.query<{ pid: number }>('SELECT pg_backend_pid() AS pid')
            const closed = new Promise<string>((resolve) => client.once('end', () => resolve('ended')))
            await withPostgres((other) => other.query('SELECT pg_terminate_backend($1)', [rows[0].pid]), URL)
            return closed
        }, URL)

        await expect(ended).resolves.toBe('ended')
    })
})

describe('keepRunningContainers', () => {
    it.each([
        ['the posthog project', '', COMPOSE],
        [
            'a project named docker-compose, after the profile banner',
            "echo '▶ docker-compose: profiles: temporal' && ",
            'docker compose -p docker-compose -f docker-compose.dev.yml -f docker-compose.profiles.yml',
        ],
    ])(
        'starts the compose services of %s without recreating the running ones and leaves the rest of the config alone',
        (_case, banner, compose) => {
            const config = generatedConfig(banner + composeShell(compose, 'up --pull always -d'))

            expect(parse(keepRunningContainers(config))).toEqual({
                procs: {
                    'docker-compose': {
                        shell: banner + composeShell(compose, 'up --pull always --no-recreate -d'),
                        ready_pattern: 'docker-compose ready',
                    },
                    backend: { shell: 'bin/start-backend' },
                },
                _posthog: { intents: ['workflows'] },
            })
        }
    )

    it.each([
        ['an up call it does not know', composeShell(COMPOSE, 'up --pull missing -d')],
        ['a second up call', composeShell(COMPOSE, 'up --pull always -d', `${COMPOSE} "up" -d db && `)],
        [
            'its up call quoted and the known call only in a message',
            composeShell(COMPOSE, 'up --pull "always" -d').replace('up failed', 'up --pull always -d failed'),
        ],
        ['no docker-compose proc', ''],
    ])('refuses a config with %s, which would recreate the shared containers', (_case, shell) => {
        const config = shell ? generatedConfig(shell) : 'procs:\n  backend:\n    shell: bin/start-backend\n'

        expect(() => keepRunningContainers(config)).toThrow(StackNotReadyError)
    })
})

describe('untilMigrated', () => {
    const NEVER = new AbortController().signal

    it('returns once every table exists', async () => {
        await expect(untilMigrated([{ url: URL, table: 'cyclotron_jobs' }], 1000, 10, NEVER)).resolves.toBeUndefined()
    })

    it('names the table that is still missing when the migrations do not finish in time', async () => {
        const waited = untilMigrated(
            [
                { url: URL, table: 'cyclotron_jobs' },
                { url: URL, table: 'scenario_never_migrated' },
            ],
            0,
            10,
            NEVER
        )

        await expect(waited).rejects.toThrow(StackNotReadyError)
        await expect(waited).rejects.toThrow('has no table scenario_never_migrated')
    })

    it('stays pending while a table is missing, and returns once a migration creates it', async () => {
        const schema = `scenario_migrating_${process.pid}`
        const migrate = (sql: string): Promise<unknown> => withPostgres((client) => client.query(sql), URL)
        await migrate(`DROP SCHEMA IF EXISTS ${schema} CASCADE; CREATE SCHEMA ${schema}`)

        try {
            await expect(
                untilMigrated([{ url: URL, table: `${schema}.jobs` }], 60_000, 60_000, NEVER, () =>
                    migrate(`CREATE TABLE IF NOT EXISTS ${schema}.jobs (id int)`).then(() => undefined)
                )
            ).resolves.toBeUndefined()
        } finally {
            await migrate(`DROP SCHEMA IF EXISTS ${schema} CASCADE`)
        }
    })

    it.each([
        ['before it probes, even when the tables exist', 'cyclotron_jobs', (): AbortSignal => AbortSignal.abort()],
        ['during the retry pause', 'scenario_never_migrated', (): AbortSignal => AbortSignal.timeout(100)],
    ])('stops a cancelled run %s', async (_case, table, cancelled) => {
        await expect(untilMigrated([{ url: URL, table }], 60_000, 60_000, cancelled())).rejects.toMatchObject({
            name: expect.stringMatching(/^(AbortError|TimeoutError)$/),
        })
    })
})
