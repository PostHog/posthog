import { CardError, LoadedCard, Target, load, loadText } from '.'
import { mkdirSync, mkdtempSync, readdirSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

import { pairProblemsOf } from '../runner/pair'
import { admissionsOf } from '../runner/status'

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

const overTheLimit = {
    ...card,
    drive: {
        ...card.drive,
        ramp: [
            { scale: 1, for: '15s' },
            { scale: 41, for: '15s' },
        ],
    },
}

const emailRamp = {
    ...card,
    drive: {
        ...card.drive,
        ramp: [
            { scale: 1, for: '15s' },
            { scale: 12, for: '15s' },
        ],
    },
}

const emailLoad = { targets: { claimsPerSecond: { email: 4 } }, tolerance: 0.1 }

const sesSettings = { CDP_SES_RATE_LIMIT_CAPACITY: '500' }

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

const edgeAccepted = { name: 'edge_accepted', params: { channel: 'ses' } }

const fullTraffic = {
    ...profile,
    traffic: {
        event_email: { ratePerSecond: 3, parks: 1 },
        event_webhook: { ratePerSecond: 2 },
        transactional_email: { ratePerSecond: 1, parks: 2 },
    },
    settings: sesSettings,
    load: { targets: { claimsPerSecond: { hogflow: 8, email: 6 }, newJobsPerSecond: 6 }, tolerance: 0.1 },
}

const hogflowChaos = {
    ...card,
    drive: { ...card.drive, for: '60s', traffic: [{ name: 'event_email' }, { name: 'event_webhook' }] },
    valves: [{ ...emailWorkerKill, at: '37s' }],
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

    it.each<[string, object | string, object | string | undefined, string | string[]]>([
        ['a card that is not YAML', 'id: [', undefined, 'card: '],
        ['a card with the wrong shape', { ...card, clock: 'scheduled' }, undefined, 'clock: '],
        [
            'a card that runs paired and names a reason it runs unpaired',
            { ...card, pair: true, unpaired: 'it judges no no_loss' },
            undefined,
            'unpaired: a card that runs paired names no reason to run unpaired',
        ],
        ['a blank reason the card runs unpaired', { ...card, unpaired: ' ' }, undefined, 'unpaired: '],
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
            'a warm-up that lasts the whole drive',
            { ...card, drive: { ...card.drive, warmUp: '30s' } },
            undefined,
            'drive.warmUp: the warm-up must end before the drive does',
        ],
        [
            'a warm-up on a ramp',
            {
                ...card,
                drive: {
                    ...card.drive,
                    warmUp: '5s',
                    ramp: [
                        { scale: 1, for: '15s' },
                        { scale: 2, for: '15s' },
                    ],
                },
            },
            undefined,
            'drive.warmUp: a drive with a ramp takes no warm-up',
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
        ...['role.kill', 'role.freeze'].map((valve): [string, object, object, string] => [
            `${valve} on cdp-api while the profile runs more than one cdp-api`,
            { ...card, valves: [{ ...emailWorkerKill, valve, target: 'cdp-api' }] },
            { ...profile, replicas: { 'cdp-api': 2 } },
            `valves.0.target: ${valve} stops cdp-api replica 0 only, and the runner keeps sending every other request to it; run one cdp-api replica on this card`,
        ]),
        ...[
            ['role.kill', 'cdp-api'],
            ['role.freeze', 'cdp-cyclotron-worker-email'],
        ].map(([valve, target]): [string, object, object, string] => [
            `edge_accepted on ${valve} of ${target}`,
            { ...card, valves: [{ ...emailWorkerKill, valve, target, when: edgeAccepted }] },
            { ...profile, replicas: { 'cdp-cyclotron-worker-email': 2 } },
            "valves.0.when: edge_accepted holds an email worker's send, so it fires only role.kill or role.terminate on cdp-cyclotron-worker-email",
        ]),
        ...[
            ['role.kill', {}],
            ['role.terminate', { grace: '20s' }],
        ].map(([valve, dose]): [string, object, object, string] => [
            `edge_accepted on ${valve} while the profile runs more than one email worker`,
            { ...card, valves: [{ ...emailWorkerKill, valve, dose, when: edgeAccepted }] },
            { ...profile, replicas: { 'cdp-cyclotron-worker-email': 2 } },
            `valves.0.target: ${valve} stops cdp-cyclotron-worker-email replica 0 only, and edge_accepted can hold another replica's send; run one email worker replica on this card`,
        ]),
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
            'a terminate whose grace is longer than a stopped run waits for its release',
            {
                ...card,
                valves: [{ ...emailWorkerKill, valve: 'role.terminate', dose: { grace: '301s' } }],
            },
            undefined,
            'valves.0.dose.grace: at most 5m, so a stopped run releases the role within its release window',
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
            'a valve with neither at nor when',
            { ...card, valves: [{ ...emailWorkerKill, when: undefined }] },
            undefined,
            'valves.0: give at, when or both',
        ],
        [
            'a valve that fires inside the baseline load admission measures',
            {
                ...card,
                drive: { ...card.drive, for: '60s' },
                valves: [{ ...emailWorkerKill, when: undefined, at: '5s' }],
            },
            { ...profile, settings: sesSettings, load: emailLoad },
            "valves.0.at: the valve can fire 5s into the drive, inside the 30s fault-free baseline and the role scrape that closes it, which load admission's claim rates need; set at to 37s or later",
        ],
        [
            'a when valve with no arming delay on a profile with host admission',
            { ...card, drive: { ...card.drive, for: '60s' }, valves: [emailWorkerKill] },
            { ...profile, host: { cpuCeiling: 0.5 } },
            'valves.0.at: the valve can fire 0s into the drive, inside the 30s fault-free baseline that load and host admission measure; set at to 30s or later',
        ],
        [
            'a when valve armed before the slowest scrape that closes the baseline on a profile with claim rates',
            { ...card, drive: { ...card.drive, for: '60s' }, valves: [{ ...emailWorkerKill, at: '36s' }] },
            { ...profile, settings: sesSettings, load: emailLoad },
            "valves.0.at: the valve can fire 36s into the drive, inside the 30s fault-free baseline and the role scrape that closes it, which load admission's claim rates need; set at to 37s or later",
        ],
        [
            'a valve that fires inside the warm-up on a profile without admission',
            {
                ...card,
                drive: { ...card.drive, for: '227s', warmUp: '160s' },
                valves: [{ ...emailWorkerKill, when: undefined, at: '100s' }],
            },
            undefined,
            'valves.0.at: the valve can fire 100s into the drive, inside its 160s warm-up; set at to 160s or later',
        ],
        [
            'a valve inside the baseline after a warm-up on a profile with host admission only',
            {
                ...card,
                drive: { ...card.drive, for: '227s', warmUp: '160s' },
                valves: [{ ...emailWorkerKill, when: undefined, at: '189999ms' }],
            },
            { ...profile, host: { cpuCeiling: 0.5 } },
            'valves.0.at: the valve can fire 189.999s into the drive, inside the 160s warm-up and the 30s fault-free baseline after it that load and host admission measure; set at to 190s or later',
        ],
        [
            'a warm-up whose floor is no whole second, which the floor names in milliseconds',
            { ...card, drive: { ...card.drive, for: '30s', warmUp: '548ms' } },
            { ...profile, host: { cpuCeiling: 0.5 } },
            'drive.for: the drive ends 30s in, inside the 0.548s warm-up and the 30s fault-free baseline after it that load and host admission measure; run it for 30548ms or longer',
        ],
        [
            'a warm-up that leaves the paired control too short a baseline',
            { ...card, drive: { ...card.drive, for: '227s', warmUp: '210s' } },
            { ...profile, host: { cpuCeiling: 0.5 } },
            'drive.for: the drive ends 227s in, inside the 210s warm-up and the 30s fault-free baseline after it that load and host admission measure; run it for 240s or longer',
        ],
        [
            'a when valve armed before the slowest scrape that closes the baseline after a warm-up',
            {
                ...card,
                drive: { ...card.drive, for: '227s', warmUp: '160s' },
                valves: [{ ...emailWorkerKill, at: '190s' }],
            },
            { ...profile, settings: sesSettings, load: emailLoad },
            "valves.0.at: the valve can fire 190s into the drive, inside the 160s warm-up, the 30s fault-free baseline after it and the role scrape that closes it, which load admission's claim rates need; set at to 197s or later",
        ],
        [
            'a valve offset longer than a timer can wait',
            { ...card, valves: [{ ...emailWorkerKill, at: '2147483648ms' }] },
            undefined,
            'valves.0.at: at is past 2147483647ms, the longest a timer waits',
        ],
        [
            'a valve offset that is no duration',
            { ...card, valves: [{ ...emailWorkerKill, at: '10sec' }] },
            undefined,
            'valves.0.at: a duration such as 500ms, 30s or 5m',
        ],
        [
            'a valve armed past the end of the drive on a profile with admission',
            { ...card, drive: { ...card.drive, for: '60s' }, valves: [{ ...emailWorkerKill, at: '60s' }] },
            { ...profile, host: { cpuCeiling: 0.5 } },
            "valves.0.at: 60s is past the drive's end at 60s, so the valve never fires",
        ],
        [
            'a when predicate the runner does not know',
            { ...card, valves: [{ ...emailWorkerKill, when: { ...emailWorkerKill.when, name: 'queue_empty' } }] },
            undefined,
            'valves.0.when.name: the predicates are running_on_queue and edge_accepted',
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
            'a synthetic padding label without a backlog',
            card,
            { ...profile, synthetic: ['backlog_padding'] },
            'profile.synthetic: backlog_padding requires a backlog',
        ],
        [
            'a synthetic transactional parks label without parks',
            card,
            {
                ...profile,
                traffic: { ...profile.traffic, transactional_email: { ratePerSecond: 1 } },
                synthetic: ['transactional_email_parks'],
            },
            'profile.synthetic: transactional_email_parks requires positive transactional email parks',
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
            'a profile that turns on the intake dead-letter drain',
            card,
            { ...profile, settings: { CDP_INTAKE_DLQ_DRAIN: 'true' } },
            'profile.settings.CDP_INTAKE_DLQ_DRAIN: the reset never seeks the drain groups',
        ],
        [
            'a profile that moves an intake topic',
            card,
            { ...profile, settings: { CDP_INTAKE_TRANSACTIONAL_EMAIL_TOPIC: 'scenario_intake_email' } },
            "profile.settings.CDP_INTAKE_TRANSACTIONAL_EMAIL_TOPIC: convergence reads each intake group's whole lag",
        ],
        [
            'a profile that runs a second intake replica',
            card,
            { ...profile, replicas: { 'cdp-intake-transactional-email': 2 } },
            'profile.replicas.cdp-intake-transactional-email: each intake topic has one partition',
        ],
        [
            'a profile setting only the object prototype has',
            card,
            { ...profile, settings: { toString: 'false' } },
            'profile.settings.toString: not a setting the roles or the load producer read',
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
        [
            "an event load whose top step passes 80% of one workflow's rate limit",
            overTheLimit,
            undefined,
            'setup.teams: event_email sends 82 units a second to each team',
        ],
        [
            'an event kind listed twice, which seeds two workflows that both match its events',
            {
                ...card,
                drive: {
                    ...card.drive,
                    traffic: [{ name: 'event_email' }, { name: 'event_email' }],
                    ramp: [
                        { scale: 1, for: '15s' },
                        { scale: 21, for: '15s' },
                    ],
                },
            },
            undefined,
            'drive.traffic: event_email is listed 2 times; list each traffic kind once',
        ],
        [
            "an email load whose top step passes half of the SES limiter's refill",
            emailRamp,
            { ...profile, settings: sesSettings, load: emailLoad },
            'profile.settings.CDP_SES_RATE_LIMIT_REFILL_PER_SECOND: the email queue claims up to 53 jobs a second at the 12x step, over 50, 50% of the SES limiter refill; raise it to 106 or more',
        ],
        [
            'an SES limiter capacity under one batch for every email replica',
            card,
            {
                ...profile,
                settings: { ...sesSettings, CONSUMER_BATCH_SIZE: '100' },
                replicas: { 'cdp-cyclotron-worker-email': 6 },
                load: emailLoad,
            },
            'profile.settings.CDP_SES_RATE_LIMIT_CAPACITY: 500 cannot hold one batch for every email replica (6) at once; raise it to 600 or more',
        ],
        [
            'a load block without an email claim target on a card that sends email',
            card,
            {
                ...profile,
                settings: sesSettings,
                load: { targets: { claimsPerSecond: { hogflow: 4 } }, tolerance: 0.1 },
            },
            'profile.load.targets.claimsPerSecond.email: the SES limiter check needs it',
        ],
        [
            'a card whose traffic never reaches a queue load admission judges',
            { ...hogflowChaos, drive: { ...hogflowChaos.drive, traffic: [{ name: 'event_webhook' }] } },
            fullTraffic,
            'drive.traffic: event_webhook makes no email claims, and load admission would judge the card on them (profile.load.targets.claimsPerSecond.email); drive traffic that reaches the email queue, or run the card on a profile without that target',
        ],
        [
            'a card on a load profile whose traffic load admission cannot derive targets from',
            { ...card, drive: { ...card.drive, traffic: [{ name: 'bounce_followup' }] } },
            { ...fullTraffic, traffic: { ...fullTraffic.traffic, bounce_followup: { ratePerSecond: 1 } } },
            'profile.traffic.bounce_followup: load admission cannot derive targets from bounce_followup, since its claims per unit are not modelled',
        ],
        [
            'a load profile with a malformed entry for traffic the card does not drive',
            card,
            {
                ...fullTraffic,
                traffic: { ...fullTraffic.traffic, event_webhook: { ratePerSecond: 0 } },
                load: { ...fullTraffic.load, targets: { claimsPerSecond: { hogflow: 8, email: 60 } } },
            },
            'profile.traffic.event_webhook.ratePerSecond: ',
        ],
        [
            'a load block without an email claim target and an SES limiter capacity under one batch',
            card,
            { ...profile, load: { targets: { claimsPerSecond: { hogflow: 4 } }, tolerance: 0.1 } },
            [
                'profile.load.targets.claimsPerSecond.email: the SES limiter check needs it',
                'profile.settings.CDP_SES_RATE_LIMIT_CAPACITY: 50 cannot hold one batch for every email replica (1) at once; raise it to 500 or more',
            ],
        ],
    ])('rejects %s', (_name, content, profileContent, problem) => {
        expect(problemsOf(content, profileContent)).toEqual([problem].flat().map((one) => expect.stringContaining(one)))
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

    it("finds a profile's alert files relative to the profile, wherever the runner starts", () => {
        const alerts = { rules: 'alerts/rules.yaml', labels: '../labels.yaml', exclude: ['SyntheticLeftOut'] }
        mkdirSync(path.join(dir, 'runner', 'alerts'), { recursive: true })
        const rules = write('runner/alerts/rules.yaml', 'groups: []\n')
        const labels = write('labels.yaml', 'labels: {}\n')
        const profilePath = write('runner/profile.yaml', { ...profile, alerts })

        expect(load(write('card.yaml', card), { profilePath }).alerts).toEqual({
            rules,
            labels,
            exclude: ['SyntheticLeftOut'],
        })
    })

    it.each(['rules', 'labels'] as const)('changes the profile hash when the alert %s file changes', (kind) => {
        const alerts = { rules: 'rules.yaml', labels: 'labels.yaml' }
        write(alerts.rules, 'groups: []\n')
        write(alerts.labels, 'labels: {}\n')
        const before = loadCard(card, { ...profile, alerts })

        write(alerts[kind], kind === 'rules' ? 'groups: []\n\n' : 'labels: { stage: test }\n')
        const after = loadCard(card, { ...profile, alerts })

        expect(after.profileHash).not.toBe(before.profileHash)
        expect(after.cardHash).not.toBe(before.cardHash)
    })

    it('refuses an alerts profile on the dev target, and one read from text with no directory for its files', () => {
        const alerts = { rules: 'rules.yaml', labels: 'labels.yaml', exclude: [] }
        const problemsOfText = (): string[] => {
            try {
                loadText('card.yaml', { card: stringify(card), profile: stringify({ ...profile, alerts }) })
            } catch (error) {
                if (error instanceof CardError) {
                    return error.problems
                }
                throw error
            }
            throw new Error('the card loaded')
        }

        expect({
            dev: problemsOf(devCard, { ...devProfile, alerts }, 'dev'),
            text: problemsOfText(),
        }).toEqual({
            dev: [
                'profile.alerts: the dev target exposes no role metrics to scrape, so only --target local runs alerts',
            ],
            text: [
                'profile.alerts: a profile read from text has no directory to resolve its rules and label map against',
            ],
        })
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

    it.each<[string, object, object]>([
        ['an event load spread over enough teams', { ...overTheLimit, setup: { teams: 2 } }, profile],
        [
            'an event load under a rate limit the profile raises',
            overTheLimit,
            { ...profile, settings: { CDP_RATE_LIMITER_REFILL_RATE: '1000' } },
        ],
        [
            'an event load under a quoted rate limit the profile raises',
            overTheLimit,
            { ...profile, settings: { CDP_RATE_LIMITER_REFILL_RATE: '"1000"' } },
        ],
        [
            'a transactional load, which no workflow rate limit slows',
            {
                ...overTheLimit,
                drive: { ...overTheLimit.drive, traffic: [{ name: 'transactional_email' }] },
                invariants: [{ name: 'at_least_once' }, { name: 'refused_at_intake' }],
            },
            { ...profile, traffic: { transactional_email: { ratePerSecond: 2 } } },
        ],
        [
            'an email load under half of a refill the profile raises',
            emailRamp,
            {
                ...profile,
                settings: { ...sesSettings, CDP_SES_RATE_LIMIT_REFILL_PER_SECOND: '120' },
                load: emailLoad,
            },
        ],
        [
            'an email load at exactly half of the refill',
            {
                ...emailRamp,
                drive: {
                    ...emailRamp.drive,
                    ramp: [
                        { scale: 1, for: '15s' },
                        { scale: 10, for: '15s' },
                    ],
                },
            },
            {
                ...profile,
                settings: { ...sesSettings, CDP_SES_RATE_LIMIT_REFILL_PER_SECOND: '110' },
                load: { targets: { claimsPerSecond: { email: 5 } }, tolerance: 0.1 },
            },
        ],
        [
            'a load block on a card that sends no email, which the SES limiter never slows',
            { ...card, drive: { ...card.drive, traffic: [{ name: 'event_webhook' }] } },
            {
                ...profile,
                traffic: { event_webhook: { ratePerSecond: 2 } },
                load: { targets: { claimsPerSecond: { hogflow: 4 } }, tolerance: 0.1 },
            },
        ],
        ['a profile that runs more than one cdp-api', card, { ...profile, replicas: { 'cdp-api': 3 } }],
        [
            'a when valve armed once the slowest scrape that closes the baseline is in',
            { ...card, drive: { ...card.drive, for: '60s' }, valves: [{ ...emailWorkerKill, at: '37s' }] },
            { ...profile, settings: sesSettings, load: emailLoad, host: { cpuCeiling: 0.5 } },
        ],
        [
            'a when valve armed once the slowest scrape that closes the baseline after a warm-up is in',
            {
                ...card,
                drive: { ...card.drive, for: '227s', warmUp: '160s' },
                valves: [{ ...emailWorkerKill, at: '197s' }],
            },
            { ...profile, settings: sesSettings, load: emailLoad, host: { cpuCeiling: 0.5 } },
        ],
        [
            'a valve at the end of the baseline after a warm-up whose sum has no exact float',
            {
                ...card,
                drive: { ...card.drive, for: '60s', warmUp: '548ms' },
                valves: [{ ...emailWorkerKill, when: undefined, at: '30548ms' }],
            },
            { ...profile, host: { cpuCeiling: 0.5 } },
        ],
        [
            'a valve-free drive shorter than the floor whose warm-up is spelled 0s, which runs as one without a warm-up',
            { ...card, drive: { ...card.drive, for: '35s', warmUp: '0s' }, valves: [] },
            { ...profile, settings: sesSettings, load: emailLoad, host: { cpuCeiling: 0.5 } },
        ],
        [
            'a when valve armed at the end of the baseline on a profile with host admission only',
            { ...card, drive: { ...card.drive, for: '60s' }, valves: [{ ...emailWorkerKill, at: '30s' }] },
            { ...profile, host: { cpuCeiling: 0.5 } },
        ],
        [
            'a valve inside the baseline on a profile without admission',
            { ...card, valves: [{ ...emailWorkerKill, when: undefined, at: '5s' }] },
            profile,
        ],
        [
            'a kill valve on another role while the profile runs more than one cdp-api',
            { ...card, valves: [emailWorkerKill] },
            { ...profile, replicas: { 'cdp-api': 2 } },
        ],
        [
            'a terminate armed on edge_accepted while the profile runs one email worker',
            {
                ...card,
                valves: [{ ...emailWorkerKill, valve: 'role.terminate', dose: { grace: '20s' }, when: edgeAccepted }],
            },
            profile,
        ],
    ])('loads %s', (_name, content, profileContent) => {
        expect(loadCard(content, profileContent).card.id).toBe(card.id)
    })

    const settings = { CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS: '10000', CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS: '30000' }

    it.each<[string, [object, object], [object, object], boolean]>([
        ['leaves out the gates', [card, profile], [{ ...card, gates: { duplicate_sends: 3 } }, profile], true],
        ['leaves out the cloud pair', [card, profile], [{ ...card, pair: true }, profile], true],
        ['leaves out the seed opt-in', [card, profile], [{ ...card, seedable: true }, profile], true],
        [
            'leaves out why the card runs unpaired',
            [card, profile],
            [{ ...card, unpaired: 'it judges no no_loss' }, profile],
            true,
        ],
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

    it('runs every shipped card that applies valves as a pair, or names why it runs unpaired', () => {
        const shipped = readdirSync(__dirname)
            .filter((file) => file.endsWith('.yaml'))
            .map((file) => load(path.join(__dirname, file)))
            .filter(({ card }) => card.valves.length > 0)

        expect(
            shipped.filter(({ card }) => !card.pair && card.unpaired === undefined).map(({ card }) => card.id)
        ).toEqual([])
        expect(shipped.filter(({ card }) => card.pair).flatMap((loaded) => pairProblemsOf(loaded, true))).toEqual([])
    })

    it('admits a chaos card on a full-traffic profile against the targets its own traffic derives', () => {
        const { admission } = loadCard(hogflowChaos, fullTraffic)
        const baseline = {
            seconds: 30,
            scrapedSeconds: 30,
            claimsPerSecond: { hogflow: 8, email: 3 },
            newJobsPerSecond: 5,
        }

        expect(admissionsOf(admission, baseline)).toEqual([
            { name: 'load', passed: true, reason: 'every baseline rate within 10% of its target' },
        ])
    })

    it.each([
        ['keeps', undefined, 1],
        ['scales', 0.25, 0.25],
    ] as const)('%s the offered rates and targets for a card that drives the full profile', (_, scale, factor) => {
        const { admission, profile } = loadCard(
            {
                ...card,
                drive: {
                    ...card.drive,
                    traffic: [{ name: 'transactional_email' }, { name: 'event_webhook' }, { name: 'event_email' }],
                },
                invariants: [{ name: 'at_least_once' }, { name: 'refused_at_intake' }],
            },
            scale === undefined ? fullTraffic : { ...fullTraffic, scale }
        )

        expect(profile.traffic).toEqual(
            Object.fromEntries(
                Object.entries(fullTraffic.traffic).map(([kind, shape]) => [
                    kind,
                    { ...shape, ratePerSecond: shape.ratePerSecond * factor },
                ])
            )
        )
        const {
            claimsPerSecond: { hogflow, email },
            newJobsPerSecond,
        } = fullTraffic.load.targets
        expect(admission.load?.targets).toEqual({
            claimsPerSecond: { hogflow: hogflow * factor, email: email * factor },
            newJobsPerSecond: newJobsPerSecond * factor,
        })
    })

    it.each(['ses-ambiguous-send', 'email-worker-killed-after-accept', 'cyclotron-enqueue-replay', 'chaos-under-load'])(
        'loads the chaos card %s on a profile with load and host admission',
        (id) => {
            const admitted = {
                ...profile,
                traffic: Object.fromEntries(
                    ['event_email', 'event_webhook', 'transactional_email'].map((name) => [name, { ratePerSecond: 2 }])
                ),
                settings: sesSettings,
                load: emailLoad,
                host: { cpuCeiling: 0.5 },
            }
            const profilePath = write('profile.yaml', admitted)

            expect(load(path.join(__dirname, `${id}.yaml`), { profilePath }).card.id).toBe(id)
        }
    )
})
