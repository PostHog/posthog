import { CardError, LoadedCard, Target, load } from '.'
import { mkdtempSync, readdirSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

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

const TWICE_DECLARED_BARS = [
    { name: 'pickup_p99_under', params: { seconds: 5, queues: ['email'] } },
    { name: 'pickup_p99_under', params: { seconds: 10, queues: ['hogflow'] } },
]

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

    const loadCard = (content: object | string, profileContent?: object | string, target?: Target): LoadedCard =>
        load(write('card.yaml', content), {
            profilePath: profileContent ? write('profile.yaml', profileContent) : undefined,
            target,
        })

    const problemsOf = (content: object | string, profileContent?: object | string, target?: Target): string[] => {
        try {
            loadCard(content, profileContent, target)
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
            'an unknown bar',
            { ...card, bars: [{ name: 'writer_iops_under' }] },
            undefined,
            'bars.0.name: unknown bar writer_iops_under',
        ],
        [
            'bar params its definition refuses',
            { ...card, bars: [{ name: 'writer_cpu_under', params: { percent: 120 } }] },
            undefined,
            'bars.0.params.percent: ',
        ],
        [
            'a bar declared twice on a card that stops on break',
            {
                ...card,
                drive: {
                    ...card.drive,
                    ramp: [
                        { scale: 1, for: '15s' },
                        { scale: 2, for: '15s' },
                    ],
                    stopOnBreak: true,
                },
                bars: TWICE_DECLARED_BARS,
            },
            undefined,
            'bars: declare each bar once on a stopOnBreak card; pickup_p99_under is declared twice',
        ],
        [
            'ramp steps that do not add up to the drive',
            {
                ...card,
                drive: {
                    ...card.drive,
                    ramp: [
                        { scale: 1, for: '10s' },
                        { scale: 10, for: '10s' },
                    ],
                },
            },
            undefined,
            'drive.ramp: the ramp steps must add up to drive.for',
        ],
        [
            'a ramp that returns to a scale it already ran',
            {
                ...card,
                drive: {
                    ...card.drive,
                    ramp: [
                        { scale: 1, for: '10s' },
                        { scale: 2, for: '10s' },
                        { scale: 1, for: '10s' },
                    ],
                },
            },
            undefined,
            'drive.ramp: each ramp step must scale higher than the one before',
        ],
        [
            'a ramp that holds a scale for two steps',
            {
                ...card,
                drive: {
                    ...card.drive,
                    ramp: [
                        { scale: 1, for: '10s' },
                        { scale: 2, for: '10s' },
                        { scale: 2, for: '10s' },
                    ],
                },
            },
            undefined,
            'drive.ramp: each ramp step must scale higher than the one before',
        ],
        [
            'a stop on break without a ramp to climb',
            { ...card, drive: { ...card.drive, stopOnBreak: true } },
            undefined,
            'drive.stopOnBreak: stopOnBreak needs a ramp of at least two steps',
        ],
        [
            'a stop on break with a step that lasts no time',
            {
                ...card,
                drive: {
                    ...card.drive,
                    ramp: [
                        { scale: 1, for: '10s' },
                        { scale: 2, for: '0ms' },
                        { scale: 3, for: '20s' },
                    ],
                    stopOnBreak: true,
                },
            },
            undefined,
            'drive.ramp: every step of a ramp that stops on a break must last longer than 0ms',
        ],
        [
            'a stop on break with a valve the stop could leave due',
            {
                ...card,
                drive: {
                    ...card.drive,
                    ramp: [
                        { scale: 1, for: '15s' },
                        { scale: 2, for: '15s' },
                    ],
                    stopOnBreak: true,
                },
                valves: [emailWorkerKill],
            },
            undefined,
            'valves: a stopOnBreak card schedules no valves, since its drive can stop before they are due',
        ],
        [
            'an unknown valve',
            { ...card, valves: [{ ...emailWorkerKill, valve: 'role.melt' }] },
            undefined,
            'valves.0.valve: unknown valve role.melt',
        ],
        [
            'a dose its valve refuses',
            {
                ...card,
                valves: [
                    { ...emailWorkerKill, valve: 'pg.drop_connections', target: 'postgres', dose: { share: 'all' } },
                ],
            },
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
            'bounced_suppressed without a bounce',
            {
                ...card,
                valves: [
                    { ...emailWorkerKill, valve: 'ses.reject', target: 'ses', dose: { type: 'rejected', share: 0.3 } },
                ],
                invariants: [{ name: 'at_least_once' }, { name: 'bounced_suppressed' }],
            },
            undefined,
            'invariants.1.name: bounced_suppressed needs a ses.reject entry with type bounce',
        ],
        [
            'transactional traffic with no verdict on intake refusals',
            { ...card, drive: { ...card.drive, traffic: [{ name: 'transactional_email' }] } },
            { ...profile, traffic: { transactional_email: { ratePerSecond: 2 } } },
            'invariants: transactional_email counts a unit its intake refused as offered, so the card needs refused_at_intake',
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
            'a second cdp-api, which no offer would reach',
            card,
            { ...profile, replicas: { 'cdp-api': 2 } },
            'profile.replicas.cdp-api: cdp-api runs once, since every intake offer goes to replica 0',
        ],
        [
            'a backlog whose state sizes shrink toward p99',
            card,
            {
                ...profile,
                backlog: {
                    teams: 1,
                    jobs: { hogflow: 10 },
                    stateBytes: { p50: 4000, p90: 1000, p99: 8000 },
                    compressibility: 0.5,
                    parkFor: '10080m',
                    tolerance: 0.01,
                },
            },
            'profile.backlog.stateBytes: p50, p90 and p99 must not decrease',
        ],
        [
            'a backlog without a queue',
            card,
            {
                ...profile,
                backlog: {
                    teams: 1,
                    jobs: {},
                    stateBytes: { p50: 1000, p90: 4000, p99: 8000 },
                    compressibility: 0.5,
                    parkFor: '10080m',
                    tolerance: 0.01,
                },
            },
            'profile.backlog.jobs: name at least one queue',
        ],
        [
            'a load target that is not a positive rate',
            card,
            { ...profile, load: { targets: { claimsPerSecond: { email: 0 } }, tolerance: 0.1 } },
            'profile.load.targets.claimsPerSecond.email: ',
        ],
        [
            'a load block without a target',
            card,
            { ...profile, load: { targets: { claimsPerSecond: {} }, tolerance: 0.1 } },
            'profile.load.targets: name at least one target',
        ],
        [
            'a load target on a queue Cyclotron does not serve',
            card,
            { ...profile, load: { targets: { claimsPerSecond: { sms: 4 } }, tolerance: 0.1 } },
            'profile.load.targets.claimsPerSecond.sms: ',
        ],
        [
            'a new jobs target that is not a positive rate',
            card,
            { ...profile, load: { targets: { claimsPerSecond: { email: 4 }, newJobsPerSecond: -1 }, tolerance: 0.1 } },
            'profile.load.targets.newJobsPerSecond: ',
        ],
        [
            'a load tolerance over 1',
            card,
            { ...profile, load: { ...{ targets: { claimsPerSecond: { email: 4 } }, tolerance: 0.1 }, tolerance: 1.5 } },
            'profile.load.tolerance: ',
        ],
        ['a host CPU ceiling over 1', card, { ...profile, host: { cpuCeiling: 1.2 } }, 'profile.host.cpuCeiling: '],
        [
            'a profile that uses a YAML alias',
            card,
            'name: synthetic\ntraffic: &loop { event_email: { ratePerSecond: 2 }, again: *loop }\nsettings: {}\n',
            'profile: Alias resolution is disabled',
        ],
    ])('rejects %s', (_name, content, profileContent, problem) => {
        expect(problemsOf(content, profileContent)).toEqual([expect.stringContaining(problem)])
    })

    const devCard = {
        ...card,
        profile: 'dev',
        drive: { for: '11s', traffic: [{ name: 'capture_webhook' }] },
        convergeWithin: '10m',
        invariants: [{ name: 'at_least_once' }, { name: 'duplicate_sends' }, { name: 'refused_at_intake' }],
        gates: { duplicate_sends: 0, refused_at_intake: 0 },
    }
    const devProfile = { name: 'dev', traffic: { capture_webhook: { ratePerSecond: 1 } } }
    const devAt = (ratePerSecond: number): object => ({
        ...devProfile,
        traffic: { capture_webhook: { ratePerSecond } },
    })

    it.each<[string, object, object, string]>([
        [
            'a traffic kind other than capture_webhook',
            { ...devCard, drive: card.drive },
            profile,
            'drive.traffic: dev does not run event_email',
        ],
        ['a valve', { ...devCard, valves: [emailWorkerKill] }, devProfile, 'valves: dev does not run role.kill'],
        [
            'a bar',
            { ...devCard, bars: [TWICE_DECLARED_BARS[0]] },
            devProfile,
            'bars: dev does not run pickup_p99_under',
        ],
        [
            'a measurement of local roles',
            { ...devCard, measure: [{ name: 'role_cpu_seconds' }] },
            devProfile,
            'measure: dev does not run role_cpu_seconds',
        ],
        [
            'profile settings',
            devCard,
            { ...devProfile, settings: { CDP_FETCH_RETRIES: '1' } },
            'profile: dev does not run settings',
        ],
        ['a host block', devCard, { ...devProfile, host: { cpuCeiling: 0.5 } }, 'profile: dev does not run host'],
        [
            'parked flows, which the workflow on dev does not have',
            devCard,
            { ...devProfile, traffic: { capture_webhook: { ratePerSecond: 1, parks: 2 } } },
            'profile: dev does not run parks',
        ],
        ['a second project', { ...devCard, setup: { teams: 2 } }, devProfile, 'setup.teams: '],
        [
            'the same traffic twice, whose first offers would start together',
            {
                ...devCard,
                drive: { ...devCard.drive, traffic: [{ name: 'capture_webhook' }, { name: 'capture_webhook' }] },
            },
            devProfile,
            'drive.traffic: dev drives one traffic entry',
        ],
        ['a rate above its cap', devCard, devAt(11), 'drive: 11 units a second is above the dev cap'],
        [
            'a ramp whose top step is above the rate cap',
            {
                ...devCard,
                drive: {
                    ...devCard.drive,
                    for: '2m',
                    ramp: [
                        { scale: 1, for: '1m' },
                        { scale: 3, for: '1m' },
                    ],
                },
            },
            devAt(4),
            'drive: 12 units a second',
        ],
        [
            'more units than its cap',
            { ...devCard, drive: { ...devCard.drive, for: '10m' } },
            devAt(4),
            'drive: 2400 units is above the dev cap',
        ],
        [
            'more units than its cap once each step is rounded as the generator schedules it',
            {
                ...devCard,
                drive: {
                    ...devCard.drive,
                    for: '299950ms',
                    ramp: [
                        { scale: 0.5, for: '199900ms' },
                        { scale: 1, for: '100050ms' },
                    ],
                },
            },
            devAt(10),
            'drive: 2001 units is above the dev cap',
        ],
        ['a drive longer than 10m', { ...devCard, drive: { ...devCard.drive, for: '11m' } }, devAt(1), 'drive.for: '],
        [
            'a convergence window shorter than receipts take to become queryable',
            { ...devCard, convergeWithin: '30s' },
            devProfile,
            'convergeWithin: dev allows 5m at least',
        ],
        [
            'a ramp step shorter than a minute, where rounding bunches offers',
            {
                ...devCard,
                drive: {
                    ...devCard.drive,
                    for: '90s',
                    ramp: [
                        { scale: 1, for: '1m' },
                        { scale: 2, for: '30s' },
                    ],
                },
            },
            devProfile,
            'drive.ramp: each dev step lasts 1m at least',
        ],
    ])('the dev target refuses %s', (_name, content, profileContent, problem) => {
        expect(problemsOf(content, profileContent, 'dev')).toEqual([expect.stringContaining(problem)])
    })

    it('refuses capture_webhook on the local target, the one cloud run hosts use too', () => {
        expect(problemsOf(devCard, devProfile)).toEqual([
            'drive.traffic: capture_webhook sends to a deployment, so only --target dev runs it',
        ])
    })

    it('reports a profile path it cannot read as a problem of the card', () => {
        expect(() => load(write('card.yaml', card), { profilePath: dir })).toThrow(
            expect.objectContaining({ problems: [expect.stringMatching(/^profile: .*EISDIR/)] })
        )
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

    it('accepts a bar declared twice with different params on a card that does not stop on break', () => {
        expect(loadCard({ ...card, bars: TWICE_DECLARED_BARS }).card.bars).toEqual(TWICE_DECLARED_BARS)
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

    it.each([
        ...readdirSync(__dirname)
            .filter((file) => file.endsWith('.yaml'))
            .map((file) => [file, 'local'] as const),
        ...readdirSync(path.join(__dirname, 'dev')).map((file) => [path.join('dev', file), 'dev'] as const),
    ])('loads the shipped card %s on the %s target with the shipped definitions and profile', (file, target) => {
        expect(load(path.join(__dirname, file), { target }).card.id).toBe(path.basename(file, '.yaml'))
    })
})
