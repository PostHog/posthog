import { CardError, DEFINITIONS, Definitions, LoadedCard, load } from '.'
import { mkdtempSync, readdirSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'
import { z } from 'zod'

const definitions: Definitions = {
    ...DEFINITIONS,
    valves: [
        ...DEFINITIONS.valves,
        { name: 'pg.drop_connections', params: z.object({ share: z.number() }).strict(), target: z.string() },
        {
            name: 'ses.reject',
            params: z.object({ type: z.enum(['bounce', 'rejected']), share: z.number() }).strict(),
            target: z.string(),
        },
    ],
    invariants: [...DEFINITIONS.invariants, { name: 'bounced_suppressed', params: z.object({}).strict() }],
    measurements: [{ name: 'role_cpu_seconds', params: z.object({}).strict() }],
}

const card = {
    id: 'test-card',
    version: 1,
    clock: 'real',
    profile: 'synthetic',
    seed: 7,
    setup: { teams: 1 },
    drive: { for: '30s', traffic: [{ name: 'event_email' }] },
    convergeWithin: '2m',
    invariants: [{ name: 'at_least_once' }],
}

const profile = { name: 'synthetic', traffic: { event_email: { ratePerSecond: 2 } }, settings: {} }

const emailWorkerKill = {
    valve: 'role.kill',
    target: 'cdp-cyclotron-worker-email',
    dose: {},
    when: { name: 'running_on_queue', params: { queue: 'email', atLeast: 1 } },
    for: '1s',
}

describe('load', () => {
    let dir: string

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-cards-'))
    })

    const write = (name: string, content: object | string): string => {
        const file = path.join(dir, name)
        writeFileSync(
            file,
            typeof content === 'string' ? content : stringify(content, { aliasDuplicateObjects: false })
        )
        return file
    }

    const loadCard = (content: object | string, profileContent?: object | string): LoadedCard =>
        load(write('card.yaml', content), {
            definitions,
            profilePath: profileContent ? write('profile.yaml', profileContent) : undefined,
        })

    const problemsOf = (content: object | string, profileContent?: object | string): string[] => {
        try {
            loadCard(content, profileContent)
        } catch (error) {
            if (error instanceof CardError) {
                return error.problems
            }
            throw error
        }
        throw new Error('the card loaded')
    }

    it.each<[string, object | string, object | string | undefined, string]>([
        ['a card that is not YAML', 'id: [', undefined, 'card: '],
        ['a card with the wrong shape', { ...card, clock: 'scheduled' }, undefined, 'clock: '],
        [
            'an unknown traffic kind',
            { ...card, drive: { ...card.drive, traffic: [{ name: 'event_sms' }] } },
            undefined,
            'drive.traffic.0.name: unknown traffic kind event_sms',
        ],
        [
            'an unknown invariant',
            { ...card, invariants: [{ name: 'exactly_twice' }] },
            undefined,
            'invariants.0.name: unknown invariant exactly_twice',
        ],
        [
            'invariant params its definition refuses',
            { ...card, invariants: [{ name: 'at_least_once', params: { within: '5s' } }] },
            undefined,
            'invariants.0.params: ',
        ],
        [
            'an unknown measurement',
            { ...card, measure: [{ name: 'queue_depth' }] },
            undefined,
            'measure.0.name: unknown measurement queue_depth',
        ],
        [
            'an unknown valve',
            { ...card, valves: [{ ...emailWorkerKill, valve: 'role.melt' }] },
            undefined,
            'valves.0.valve: unknown valve role.melt',
        ],
        [
            'a dose its valve refuses',
            { ...card, valves: [{ ...emailWorkerKill, valve: 'pg.drop_connections', dose: { share: 'all' } }] },
            undefined,
            'valves.0.dose.share: ',
        ],
        [
            'a kill aimed at something that is not a role',
            { ...card, valves: [{ ...emailWorkerKill, target: 'postgres' }] },
            undefined,
            'valves.0.target: ',
        ],
        [
            'running_on_queue on a queue the probe does not count',
            {
                ...card,
                valves: [
                    { ...emailWorkerKill, when: { name: 'running_on_queue', params: { queue: 'hog', atLeast: 1 } } },
                ],
            },
            undefined,
            'valves.0.when.params.queue: ',
        ],
        [
            'both at and when',
            { ...card, valves: [{ ...emailWorkerKill, at: '5s' }] },
            undefined,
            'valves.0: exactly one of at, when',
        ],
        [
            'a when predicate other than running_on_queue',
            { ...card, valves: [{ ...emailWorkerKill, when: { ...emailWorkerKill.when, name: 'queue_empty' } }] },
            undefined,
            'valves.0.when.name: running_on_queue is the only predicate',
        ],
        [
            'running_on_queue without its queue',
            { ...card, valves: [{ ...emailWorkerKill, when: { name: 'running_on_queue', params: { atLeast: 1 } } }] },
            undefined,
            'valves.0.when.params.queue: ',
        ],
        [
            'a kill whose convergeWithin does not outlast the janitor bound',
            { ...card, valves: [emailWorkerKill], convergeWithin: '47s' },
            undefined,
            'convergeWithin: 47s must exceed 47s',
        ],
        [
            'a kill bound raised by the profile settings',
            { ...card, valves: [emailWorkerKill], convergeWithin: '60s' },
            { ...profile, settings: { CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: '60000' } },
            'convergeWithin: 60s must exceed 77s',
        ],
        [
            'a stall timeout the janitor would read as no number',
            { ...card, valves: [emailWorkerKill], convergeWithin: '18s' },
            { ...profile, settings: { CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: '' } },
            'profile.settings.CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: not a number of milliseconds at or above zero',
        ],
        [
            'a stall timeout with a leading point, which the service reads as no number',
            { ...card, valves: [emailWorkerKill], convergeWithin: '18s' },
            { ...profile, settings: { CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: '.5' } },
            'profile.settings.CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: not a number of milliseconds at or above zero',
        ],
        [
            'a negative sweep interval',
            { ...card, valves: [emailWorkerKill], convergeWithin: '48s' },
            { ...profile, settings: { CYCLOTRON_NODE_JANITOR_CLEANUP_INTERVAL_MS: '-30000' } },
            'profile.settings.CYCLOTRON_NODE_JANITOR_CLEANUP_INTERVAL_MS: not a number of milliseconds at or above zero',
        ],
        [
            'a second stall whose backoff convergeWithin does not outlast',
            { ...card, valves: [emailWorkerKill, emailWorkerKill], convergeWithin: '100s' },
            undefined,
            'convergeWithin: 100s must exceed 107s',
        ],
        [
            'a kill and a connection drop, which can stall the same job',
            {
                ...card,
                valves: [
                    emailWorkerKill,
                    {
                        valve: 'pg.drop_connections',
                        target: 'postgres',
                        dose: { share: 1 },
                        when: emailWorkerKill.when,
                        for: '1s',
                    },
                ],
                convergeWithin: '100s',
            },
            undefined,
            'convergeWithin: 100s must exceed 107s',
        ],
        [
            'pg.drop_connections scheduled by at',
            {
                ...card,
                valves: [{ valve: 'pg.drop_connections', target: 'postgres', dose: { share: 1 }, at: '5s', for: '1s' }],
                convergeWithin: '2m',
            },
            undefined,
            'valves.0.at: pg.drop_connections waits for running jobs, so it takes when, not at',
        ],
        [
            'bounced_suppressed without a bounce',
            {
                ...card,
                valves: [{ ...emailWorkerKill, valve: 'ses.reject', dose: { type: 'rejected', share: 0.3 } }],
                invariants: [{ name: 'at_least_once' }, { name: 'bounced_suppressed' }],
            },
            undefined,
            'invariants.1.name: bounced_suppressed needs a ses.reject entry with type bounce',
        ],
        [
            'a profile without the traffic a card drives',
            card,
            { ...profile, traffic: {} },
            'profile.traffic.event_email: ',
        ],
        [
            'a profile the repository does not ship',
            { ...card, profile: 'prod-shape' },
            undefined,
            'profile: no shipped profile prod-shape; pass its file with --profile',
        ],
        [
            'a profile setting no role reads',
            card,
            { ...profile, settings: { CYCLOTRON_NODE_JANITOR_STALL_TIMOUT_MS: '60000' } },
            'profile.settings.CYCLOTRON_NODE_JANITOR_STALL_TIMOUT_MS: not a setting the roles or the load producer read',
        ],
        [
            'a profile setting only the object prototype has',
            card,
            { ...profile, settings: { toString: 'false' } },
            'profile.settings.toString: not a setting the roles or the load producer read',
        ],
        [
            'a profile that uses a YAML alias',
            card,
            'name: synthetic\ntraffic: &loop { event_email: { ratePerSecond: 2 }, again: *loop }\nsettings: {}\n',
            'profile: Alias resolution is disabled',
        ],
    ])('rejects %s', (_name, content, profileContent, problem) => {
        expect(problemsOf(content, profileContent)).toEqual([expect.stringContaining(problem)])
    })

    it('lists every problem in one error', () => {
        const problems = problemsOf({
            ...card,
            drive: { ...card.drive, traffic: [{ name: 'event_sms' }] },
            invariants: [{ name: 'exactly_twice' }],
        })

        expect(problems).toEqual([
            'drive.traffic.0.name: unknown traffic kind event_sms',
            'invariants.0.name: unknown invariant exactly_twice',
        ])
    })

    it.each<[string, object[]]>([
        ['one kill', [emailWorkerKill]],
        [
            'kills on two roles, which stall different jobs',
            [emailWorkerKill, { ...emailWorkerKill, target: 'cdp-cyclotron-worker-hogflow' }],
        ],
    ])('accepts %s whose convergeWithin outlasts the janitor bound', (_name, valves) => {
        expect(loadCard({ ...card, valves, convergeWithin: '48s' }).card.valves).toHaveLength(valves.length)
    })

    it('keeps the name of a profile passed from outside the repository', () => {
        expect(loadCard(card, { ...profile, name: 'measured-2026-11' }).profile.name).toBe('measured-2026-11')
    })

    it.each<[string, Record<string, string>]>([
        [
            'the settings a role reads straight from the process environment',
            { HOG_BYTECODE_CACHE_REQUIRED: 'false', HOG_BYTECODE_CACHE_REWRITE: 'false' },
        ],
        ["settings for the runner's load producer", { KAFKA_PRODUCER_LINGER_MS: '100' }],
    ])('accepts %s', (_name, settings) => {
        expect(loadCard(card, { ...profile, settings }).profile.settings).toEqual(settings)
    })

    const settings = { CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS: '10000', CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: '30000' }

    it.each<[string, [object, object], [object, object], boolean]>([
        ['leaves out the gates', [card, profile], [{ ...card, gates: { duplicate_sends: 3 } }, profile], true],
        [
            'ignores the key order of the profile settings',
            [card, { ...profile, settings }],
            [card, { ...profile, settings: Object.fromEntries(Object.entries(settings).reverse()) }],
            true,
        ],
        ['covers the seed', [card, profile], [{ ...card, seed: 8 }, profile], false],
        [
            'covers the profile',
            [card, profile],
            [card, { ...profile, traffic: { event_email: { ratePerSecond: 3 } } }],
            false,
        ],
    ])('the card hash %s', (_name, [leftCard, leftProfile], [rightCard, rightProfile], same) => {
        const left = loadCard(leftCard, leftProfile).cardHash
        const right = loadCard(rightCard, rightProfile).cardHash

        expect(left === right).toBe(same)
    })

    it.each(readdirSync(__dirname).filter((file) => file.endsWith('.yaml')))(
        'loads the shipped card %s with the shipped definitions and profile',
        (file) => {
            expect(load(path.join(__dirname, file)).card.id).toBe(path.basename(file, '.yaml'))
        }
    )
})
