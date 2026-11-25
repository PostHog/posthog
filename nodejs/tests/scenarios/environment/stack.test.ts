import { parse } from 'yaml'

import { defaultConfig } from '~/common/config/config'

import { StackNotReadyError, keepRunningContainers, untilMigrated, withPostgres } from './stack'

const URL = defaultConfig.CYCLOTRON_NODE_DATABASE_URL!

const COMPOSE = 'docker compose -p posthog -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile temporal'

const generatedConfig = (composeShell: string): string =>
    `procs:\n  docker-compose:\n    shell: ${JSON.stringify(composeShell)}\n    ready_pattern: docker-compose ready\n  backend:\n    shell: bin/start-backend\n_posthog:\n  intents: [workflows]\n`

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
    it('starts the compose services without recreating the running ones and leaves the rest of the config alone', () => {
        const shell = `${COMPOSE} up --pull always -d || { echo "failed"; exit 1; } && echo "docker-compose ready" && ${COMPOSE} logs --tail=100 -f`

        expect(parse(keepRunningContainers(generatedConfig(shell)))).toEqual({
            procs: {
                'docker-compose': {
                    shell: `${COMPOSE} up --no-recreate -d || { echo "failed"; exit 1; } && echo "docker-compose ready" && ${COMPOSE} logs --tail=100 -f`,
                    ready_pattern: 'docker-compose ready',
                },
                backend: { shell: 'bin/start-backend' },
            },
            _posthog: { intents: ['workflows'] },
        })
    })

    it.each([
        ['an up call it does not know', `${COMPOSE} up --pull missing -d && echo "docker-compose ready"`],
        ['no docker-compose proc', ''],
    ])('refuses a config with %s, which would recreate the shared containers', (_case, shell) => {
        const config = shell ? generatedConfig(shell) : 'procs:\n  backend:\n    shell: bin/start-backend\n'

        expect(() => keepRunningContainers(config)).toThrow(StackNotReadyError)
    })
})

describe('untilMigrated', () => {
    it('returns once every table exists', async () => {
        await expect(untilMigrated([{ url: URL, table: 'cyclotron_jobs' }], 1000, 10)).resolves.toBeUndefined()
    })

    it('names the table that is still missing when the migrations do not finish in time', async () => {
        const waited = untilMigrated(
            [
                { url: URL, table: 'cyclotron_jobs' },
                { url: URL, table: 'scenario_never_migrated' },
            ],
            50,
            10
        )

        await expect(waited).rejects.toThrow(StackNotReadyError)
        await expect(waited).rejects.toThrow('has no table scenario_never_migrated')
    })
})
