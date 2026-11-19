import { createHash } from 'crypto'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

import { parseJSON } from '~/common/utils/json-parse'

import { FAILOVER_RELEASE_WITHIN_MS } from '../environment/failover'
import { FakeProjectApi, startFakeProjectApi } from '../scorecard/fake-project-api'
import { storeTokenPathOf } from '../store/client'
import { TestStore, UNREACHABLE_STORE, startTestStore, storeEnvOf } from '../store/test-store'
import { FakeCloud, FakeCloudOptions, ReaderMinute } from './fake-cloud'
import { PROFILE } from './fixtures'
import { STOP_TIMEOUT_S, STOP_WAIT_MS } from './host'
import { lease } from './lease'
import { Controller, main } from './main'
import { loadRunInputs } from './profile'
import { POLL_MS } from './stack'

const T = new Date('2026-03-02T10:00:00.000Z')
const HOUR_MS = 60 * 60 * 1000
const COMMIT = 'c0ffee0000000000000000000000000000000000'
const OWNER = 'arn:aws:sts::000000000000:assumed-role/scenario-run-controller/person'
const OTHER_ACCOUNT = '111111111111'
const FAILOVER_CARD = 'cyclotron-failover-under-load'
const RUNNER_PROFILE = readFileSync(path.join(__dirname, '..', 'profiles', 'synthetic.yaml'), 'utf8')

type Setup = {
    profile?: (profile: typeof PROFILE) => unknown
    cloud?: Partial<FakeCloudOptions>
    onMaster?: boolean
    arrange?: (cloud: FakeCloud) => void
    env?: NodeJS.ProcessEnv
    uncommitted?: string
}

const sha256 = (text: string): string => createHash('sha256').update(text).digest('hex')

const minutes = (from: number, to: number, max: number, avg: number): ReaderMinute[] =>
    Array.from({ length: to - from + 1 }, (_, i) => ({ minute: from + i, max, avg }))

const IDLE_THEN_PROMOTED = [
    ...minutes(-5, -3, 1, 1),
    ...minutes(-2, -2, 2, 1.6),
    ...minutes(-1, -1, 1.5, 1.2),
    ...minutes(0, 0, 4, 2.4),
    ...minutes(1, 2, 8, 6),
]

describe('cloud controller', () => {
    let dir: string
    let now: Date
    let cloud: FakeCloud
    let out: string[]
    let err: string[]
    let interrupt: (() => void) | undefined
    let onSleep: (() => Promise<void> | void) | undefined
    let api: FakeProjectApi

    const profilePath = (): string => path.join(dir, 'profile.yaml')

    function prepare({
        profile = (p) => p,
        cloud: options = {},
        onMaster = true,
        arrange = () => undefined,
        env = {},
        uncommitted,
    }: Setup = {}): {
        controller: Controller
    } {
        writeFileSync(profilePath(), stringify(profile(structuredClone(PROFILE))))
        writeFileSync(path.join(dir, 'runner.yaml'), RUNNER_PROFILE)
        cloud = new FakeCloud({ now: () => now, ...options })
        arrange(cloud)
        const controller: Controller = {
            aws: cloud,
            origin: {
                head: () => COMMIT,
                onMaster: (commit) => Promise.resolve(onMaster && commit === COMMIT),
                cardAt: (commit, id) => {
                    if (commit !== COMMIT || id === uncommitted) {
                        throw new Error(
                            `fatal: path 'nodejs/tests/scenarios/cards/${id}.yaml' does not exist in '${commit}'`
                        )
                    }
                    return readFileSync(path.join(__dirname, '..', 'cards', `${id}.yaml`), 'utf8')
                },
            },
            now: () => now,
            sleep: async (ms) => {
                now = new Date(now.getTime() + ms)
                await onSleep?.()
            },
            onInterrupt: (handler) => {
                interrupt = handler
                return () => {
                    interrupt = undefined
                }
            },
            env: { HOME: dir, ...env },
            print: (line) => out.push(line),
            warn: (line) => err.push(line),
        }
        return { controller }
    }

    async function leaseAt(at: Date, controller: Controller): Promise<string> {
        now = at
        const manifest = await lease(
            controller,
            { ...loadRunInputs(profilePath()), card: { id: FAILOVER_CARD, failsOver: true } },
            {
                owner: OWNER,
                commit: COMMIT,
            }
        )
        return manifest.runId
    }

    const leasedRunId = (): string =>
        /^Leased run (\S+) until/.exec(out.find((line) => line.startsWith('Leased run'))!)![1]

    const lastReceipt = (runId: string): unknown => {
        const key = [...cloud.objects.keys()]
            .filter((name) => name.startsWith(`runs/${runId}/receipts/`))
            .sort()
            .at(-1)
        return parseJSON(cloud.objects.get(key!)!)
    }

    const released = (runId: string): number => out.filter((line) => line === `Released run ${runId}.`).length

    const schedulesFor = (runId: string): string[] =>
        [...cloud.schedules.values()]
            .filter(({ target }) => target.Input.includes(runId))
            .map(({ expression }) => expression)
            .sort()

    const published = (): Record<string, unknown> => {
        expect(api.captured).toHaveLength(1)
        return api.captured[0].properties
    }

    const cardOf = (runId: string): { startedAt: number; endedAt: number } => {
        const key = [...cloud.objects.keys()].find(
            (key) => key.startsWith(`runs/${runId}/evidence/run/`) && key.endsWith('/scorecard.json')
        )!
        const { event } = parseJSON(cloud.objects.get(key)!) as { event: { started_at: string; ended_at: string } }
        return { startedAt: Date.parse(event.started_at), endedAt: Date.parse(event.ended_at) }
    }

    beforeAll(async () => {
        api = await startFakeProjectApi()
    })

    afterAll(() => api.close())

    beforeEach(() => {
        api.captured.length = 0
        dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-cloud-'))
        now = T
        out = []
        err = []
        interrupt = undefined
        onSleep = undefined
    })

    afterEach(() => rmSync(dir, { recursive: true, force: true }))

    it.each<[string, string, Record<string, number>, string, RegExp, RegExp]>([
        ['60m', 'the default interval', {}, '$47.86', /teardown tail.*\$5\.25/, /Monitoring logs, 0\.22 GB: \$0\.11/],
        ['120m', 'the default interval', {}, '$53.12', /teardown tail.*\$10\.50/, /Monitoring logs, 0\.22 GB: \$0\.11/],
        [
            '60m',
            'every second',
            { readerMonitoringIntervalSeconds: 1 },
            '$47.99',
            /teardown tail.*\$5\.27/,
            /Monitoring logs, 0\.43 GB: \$0\.22/,
        ],
    ])(
        'prints the itemized worst-case estimate for the fixed six-hour TTL, with a %s teardown allowance and the reader monitored at %s',
        async (allowance, _interval, monitoring, total, tail, logs) => {
            const { controller } = prepare({
                profile: (p) => ({ ...p, ...monitoring, admission: { ...p.admission, teardownAllowance: allowance } }),
            })

            await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

            expect(out.join('\n')).toContain(`Admitted estimate: ${total} of the $200 cap`)
            expect(out.join('\n')).toMatch(/reader at 32 ACU.*\$19\.20/)
            expect(out.join('\n')).toMatch(tail)
            expect(out.join('\n')).toMatch(logs)
        }
    )

    it.each<[string, Setup, number]>([
        ['the production setting when the profile names none', {}, 60],
        ['the interval the profile names', { profile: (p) => ({ ...p, readerMonitoringIntervalSeconds: 5 }) }, 5],
    ])('monitors the reader at %s and the writer every second', async (_, setup, readerInterval) => {
        const { controller } = prepare({ ...setup, env: api.credentials })
        const intervalsOf = async (stackName: string): Promise<Record<string, number>> => {
            const { StackResources } = (await cloud.call([
                'cloudformation',
                'describe-stack-resources',
                '--stack-name',
                stackName,
            ])) as { StackResources: { LogicalResourceId: string; ResourceType: string; PhysicalResourceId: string }[] }
            const instances = StackResources.filter(({ ResourceType }) => ResourceType === 'AWS::RDS::DBInstance')
            const described = await Promise.all(
                instances.map(async ({ LogicalResourceId, PhysicalResourceId }) => {
                    const { DBInstances } = (await cloud.call([
                        'rds',
                        'describe-db-instances',
                        '--db-instance-identifier',
                        PhysicalResourceId,
                    ])) as { DBInstances: { MonitoringInterval: number }[] }
                    return [LogicalResourceId, DBInstances[0].MonitoringInterval] as const
                })
            )
            return Object.fromEntries(described)
        }
        let readerAdded = false
        let atCardStart: Promise<Record<string, number>> | undefined
        cloud.beforeCall('update-stack', () => {
            readerAdded = true
        })
        cloud.beforeCall('send-command', () => {
            if (readerAdded) {
                atCardStart ??= intervalsOf(`scn-${leasedRunId()}`)
            }
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

        expect(await atCardStart).toEqual({ Writer: 1, Reader: readerInterval })
        expect(published()).toMatchObject({ reader_monitoring_interval_seconds: readerInterval })
    })

    it('runs the card it is given on the host and judges a card without a failover on its own verdict', async () => {
        const { controller } = prepare({
            profile: (p) => ({ ...p, readerAcu: { min: p.readerAcu.min, max: p.readerAcu.max } }),
            env: api.credentials,
        })

        await expect(main(['run', profilePath(), 'cyclotron-scale'], controller)).resolves.toBe(0)

        expect(published()).toMatchObject({
            card_id: 'cyclotron-scale',
            status: 'passed',
            t0_at: null,
            reader_acu_at_t0: null,
        })
    })

    it('calls a card without a failover invalid when CloudWatch answers with fewer values than timestamps', async () => {
        const { controller } = prepare({
            profile: (p) => ({ ...p, readerAcu: { min: p.readerAcu.min, max: p.readerAcu.max } }),
            cloud: { liveReaderAcu: { maxima: [1, 1, 1, 1, 1] }, shortValuesOf: 'Average' },
            env: api.credentials,
        })

        await expect(main(['run', profilePath(), 'cyclotron-scale'], controller)).resolves.toBe(2)

        expect(published()).toMatchObject({ card_id: 'cyclotron-scale', status: 'invalid' })
        expect(published().status_reason).toContain('could not read the reader capacity')
    })

    it.each<[string, string | undefined, string, Setup]>([
        ['a card that does not exist', 'no-such-card', 'no-such-card is not a card at commit', {}],
        [
            'a card that exists only in the working tree, not at the run commit',
            'cyclotron-scale',
            'cyclotron-scale is not a card at commit',
            { uncommitted: 'cyclotron-scale' },
        ],
        [
            'a card the runner profile cannot run',
            FAILOVER_CARD,
            `cards/${FAILOVER_CARD}.yaml at ${COMMIT} is not a valid card`,
            { arrange: () => writeFileSync(path.join(dir, 'runner.yaml'), 'name: empty\n') },
        ],
        [
            'a failover card under a cloud profile without the reader idle limit',
            FAILOVER_CARD,
            `${FAILOVER_CARD} fails the reader over, so the cloud profile needs readerAcu.idleMax`,
            { profile: (p) => ({ ...p, readerAcu: { min: p.readerAcu.min, max: p.readerAcu.max } }) },
        ],
        ['a card path, which the run host cannot read', '../cards/cyclotron-scale.yaml', 'card id', {}],
        ['no card', undefined, 'Usage:', {}],
    ])('refuses %s before it leases anything', async (_story, card, problem, setup) => {
        const { controller } = prepare(setup)

        await expect(main(['run', profilePath(), ...(card ? [card] : [])], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(problem)
        expect(cloud.schedules.size).toBe(0)
        expect([...cloud.objects.keys()]).toEqual([])
    })

    it('leases the run by registering both stack-delete schedules and the private inputs', async () => {
        const { controller } = prepare()

        const runId = await leaseAt(T, controller)

        expect(cloud.schedules.size).toBe(2)
        for (const { target } of cloud.schedules.values()) {
            expect(target).toEqual({
                Arn: 'arn:aws:scheduler:::aws-sdk:cloudformation:deleteStack',
                RoleArn: PROFILE.baseline.schedulerRole,
                Input: JSON.stringify({ StackName: `scn-${runId}` }),
            })
        }
        expect(schedulesFor(runId)).toEqual(['at(2026-03-02T16:00:00)', 'at(2026-03-02T17:00:00)'])
        const manifest = parseJSON(cloud.objects.get(`runs/${runId}/manifest.json`)!)
        expect(manifest).toMatchObject({
            runId,
            owner: OWNER,
            commit: COMMIT,
            expiresAt: '2026-03-02T16:00:00.000Z',
            readerIdleMaxAcu: PROFILE.readerAcu.idleMax,
        })
        expect(cloud.objects.get(`runs/${runId}/input/manifest.json`)).toEqual(
            cloud.objects.get(`runs/${runId}/manifest.json`)
        )
        for (const [file, local] of [
            ['cloud-profile.yaml', profilePath()],
            ['runner-profile.yaml', path.join(dir, 'runner.yaml')],
        ]) {
            const uploaded = cloud.objects.get(`runs/${runId}/input/${file}`)!
            expect(uploaded).toEqual(readFileSync(local, 'utf8'))
            expect(manifest.inputs[file]).toEqual(sha256(uploaded))
        }
    })

    it('deletes the schedule it created and names the run when the second schedule fails', async () => {
        const { controller } = prepare()
        cloud.failOnCall('create-schedule', 2)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(cloud.schedules.size).toBe(0)
        const runId = [...cloud.objects.keys()]
            .map((key) => /^runs\/([^/]+)\/manifest\.json$/.exec(key)?.[1])
            .find(Boolean)
        expect(err.join('\n')).toContain(`Run ${runId} was not leased`)
    })

    it('releases the lease when the run ends', async () => {
        const { controller } = prepare()

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

        const runId = leasedRunId()
        expect(released(runId)).toBe(1)
        expect(cloud.schedules.size).toBe(0)
        expect(cloud.deleteStackRequests).toEqual([])
    })

    it('runs on the profile the account pin checked, even when the file changes during the identity check', async () => {
        const { controller } = prepare()
        const call = cloud.call.bind(cloud)
        cloud.call = async (args) => {
            const result = await call(args)
            if (args.join(' ') === 'sts get-caller-identity') {
                writeFileSync(profilePath(), stringify({ ...PROFILE, account: OTHER_ACCOUNT }))
            }
            return result
        }

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

        const manifest = parseJSON(cloud.objects.get(`runs/${leasedRunId()}/input/manifest.json`)!)
        expect(manifest.account).toEqual(PROFILE.account)
    })

    it('reads the profile inputs once, so the uploads match the admitted hashes', async () => {
        const { controller } = prepare()
        const onMaster = controller.origin.onMaster
        controller.origin.onMaster = (commit) => {
            writeFileSync(path.join(dir, 'runner.yaml'), 'edited: during admission\n')
            return onMaster(commit)
        }

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

        const runId = leasedRunId()
        const manifest = parseJSON(cloud.objects.get(`runs/${runId}/input/manifest.json`)!)
        const uploaded = cloud.objects.get(`runs/${runId}/input/runner-profile.yaml`)!
        expect(uploaded).not.toContain('edited')
        expect(sha256(uploaded)).toEqual(manifest.inputs['runner-profile.yaml'])
    })

    it.each<[string, Setup, string]>([
        [
            'an estimate over the cap',
            {
                profile: (p) => ({
                    ...p,
                    admission: { ...p.admission, rates: { ...p.admission.rates, writerPerHour: 30 } },
                }),
            },
            'over the $200 cap',
        ],
        ['an identity outside the profile account', { cloud: { account: '111111111111' } }, 'account 111111111111'],
        ['a commit that is not on master', { onMaster: false }, COMMIT],
        [
            'a cap other than the fixed one',
            { profile: (p) => ({ ...p, admission: { ...p.admission, capUsd: 300 } }) },
            'admission.capUsd',
        ],
        [
            'a TTL other than the fixed one',
            { profile: (p) => ({ ...p, admission: { ...p.admission, ttlHours: 12 } }) },
            'admission.ttlHours',
        ],
        ['a region other than us-east-1', { profile: (p) => ({ ...p, region: 'eu-west-1' }) }, 'region'],
        [
            'a runner profile given as an absolute path',
            { profile: (p) => ({ ...p, runnerProfile: path.join(dir, 'runner.yaml') }) },
            'runnerProfile',
        ],
        [
            'a runner profile path through another directory',
            { profile: (p) => ({ ...p, runnerProfile: 'nested/../runner.yaml' }) },
            'runnerProfile',
        ],
        [
            'a launch template version CloudFormation does not resolve',
            { profile: (p) => ({ ...p, baseline: { ...p.baseline, hostLaunchTemplateVersion: '$Latest' } }) },
            'baseline.hostLaunchTemplateVersion',
        ],
        [
            'a reader idle limit below the reader minimum',
            { profile: (p) => ({ ...p, readerAcu: { ...p.readerAcu, idleMax: 0.5 } }) },
            'readerAcu.idleMax',
        ],
        [
            'a pooler image not pinned by digest',
            { profile: (p) => ({ ...p, pooler: { ...p.pooler, image: 'registry.example.com/pgbouncer:1' } }) },
            'pooler.image',
        ],
        [
            'a pooler setting the host owns',
            {
                profile: (p) => ({
                    ...p,
                    pooler: { ...p.pooler, settings: { ...p.pooler.settings, listen_port: 5432 } },
                }),
            },
            'pooler.settings',
        ],
        [
            'a reader monitoring interval RDS does not offer',
            { profile: (p) => ({ ...p, readerMonitoringIntervalSeconds: 2 }) },
            'readerMonitoringIntervalSeconds',
        ],
        [
            'a pooler setting that spans lines',
            {
                profile: (p) => ({
                    ...p,
                    pooler: { ...p.pooler, settings: { ...p.pooler.settings, pool_mode: 'session\nlisten_port = 1' } },
                }),
            },
            'pooler.settings',
        ],
    ])('refuses %s before it writes anything', async (_, setup, reason) => {
        const { controller } = prepare(setup)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(reason)
        expect(cloud.objects.size).toBe(0)
        expect(cloud.schedules.size).toBe(0)
    })

    const PERSON_ROLE = 'AWSReservedSSO_administrators_0123456789abcdef'

    const CONTROLLER = 'the scenario-run-controller role'
    const MISMATCH = `account ${OTHER_ACCOUNT}, and the profile names 222222222222`

    it.each<[string, string, string, string, string, (runId: string) => string[]]>([
        ['run', PERSON_ROLE, 'person', OTHER_ACCOUNT, CONTROLLER, () => ['run', profilePath(), FAILOVER_CARD]],
        [
            'cleanup <run id>',
            PERSON_ROLE,
            'person',
            OTHER_ACCOUNT,
            CONTROLLER,
            (runId) => ['cleanup', profilePath(), runId],
        ],
        [
            'run',
            'scenario-run-controller-copy',
            'person',
            OTHER_ACCOUNT,
            CONTROLLER,
            () => ['run', profilePath(), FAILOVER_CARD],
        ],
        [
            'run',
            PERSON_ROLE,
            'scenario-run-controller',
            OTHER_ACCOUNT,
            CONTROLLER,
            () => ['run', profilePath(), FAILOVER_CARD],
        ],
        [
            'cleanup <run id>',
            'scenario-run-controller',
            'person',
            '222222222222',
            MISMATCH,
            (runId) => ['cleanup', profilePath(), runId],
        ],
    ])(
        'refuses to %s as role %s with session %s for a profile naming account %s',
        async (_, role, session, profileAccount, reason, argv) => {
            const { controller } = prepare({
                profile: (p) => ({ ...p, account: profileAccount }),
                cloud: { account: OTHER_ACCOUNT },
            })
            const runId = await leaseAt(T, controller)
            cloud.role = role
            cloud.session = session
            now = new Date(T.getTime() + 6.5 * HOUR_MS)
            await cloud.call(['sts', 'get-caller-identity'])
            const objects = new Map(cloud.objects)
            const schedules = new Map(cloud.schedules)

            await expect(main(argv(runId), controller)).resolves.toBe(2)

            expect(err.join('\n')).toContain(reason)
            expect(cloud.objects).toEqual(objects)
            expect(cloud.schedules).toEqual(schedules)
            expect(released(runId)).toBe(0)
        }
    )

    it.each<[string, number, Record<string, number>, string, number]>([
        ['refuses a run far over the cap', 30, {}, '$250.86', 2],
        ['admits a run just under the cap with the reader at the default interval', 22.72, {}, '$199.90', 0],
        [
            'refuses the same run when its reader is monitored every second',
            22.72,
            { readerMonitoringIntervalSeconds: 1 },
            '$200.03',
            2,
        ],
    ])('prints the estimate and %s', async (_, writerPerHour, monitoring, total, exitCode) => {
        const { controller } = prepare({
            profile: (p) => ({
                ...p,
                ...monitoring,
                admission: { ...p.admission, rates: { ...p.admission.rates, writerPerHour } },
            }),
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(exitCode)

        expect(out.join('\n')).toContain(`Admitted estimate: ${total} of the $200 cap`)
        expect(err.join('\n').includes('The admitted estimate is over the $200 cap.')).toBe(exitCode === 2)
    })

    it.each<[string, () => void]>([
        ['after the runner profile is gone', () => rmSync(path.join(dir, 'runner.yaml'))],
        [
            'after its idle limit was edited to a negative value, below the reader minimum',
            () =>
                writeFileSync(
                    profilePath(),
                    stringify({ ...PROFILE, readerAcu: { ...PROFILE.readerAcu, idleMax: -0.5 } })
                ),
        ],
    ])('cleans up with only the cloud profile, %s', async (_, edit) => {
        const { controller } = prepare()
        const runId = await leaseAt(T, controller)
        edit()

        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(0)

        expect(released(runId)).toBe(1)
    })

    it('cleanup <run id> releases a live lease', async () => {
        const { controller } = prepare()
        const runId = await leaseAt(T, controller)
        now = new Date(T.getTime() + HOUR_MS)

        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(0)

        expect(released(runId)).toBe(1)
        expect(cloud.schedules.size).toBe(0)
    })

    it('refuses cleanup of a run id with no manifest', async () => {
        const { controller } = prepare()

        await expect(main(['cleanup', profilePath(), 'not-a-run'], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain('not-a-run')
    })

    it.each<[string, (other: string) => Record<string, unknown>]>([
        ['schedules', (other) => ({ schedules: [`scn-${other}-expiry`, `scn-${other}-expiry-retry`] })],
        ['stack', (other) => ({ stackName: `scn-${other}` })],
        ['run id', (other) => ({ runId: other })],
    ])("refuses to clean up a run whose manifest names another run's %s", async (_, swap) => {
        const { controller } = prepare()
        const runId = await leaseAt(T, controller)
        const other = await leaseAt(T, controller)
        const key = `runs/${runId}/manifest.json`
        cloud.objects.set(key, JSON.stringify({ ...parseJSON(cloud.objects.get(key)!), ...swap(other) }))

        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(runId)
        expect(released(runId)).toBe(0)
        expect(schedulesFor(other)).toHaveLength(2)
    })

    it('refuses to clean up a run id that is not a UUID', async () => {
        const { controller } = prepare()
        const runId = "x'; touch /tmp/scenario-owned; '"
        const stackName = `scn-${runId}`
        const manifest = {
            runId,
            stackName,
            schedules: [`${stackName}-expiry`, `${stackName}-expiry-retry`],
            expiresAt: T.toISOString(),
        }
        cloud.objects.set(`runs/${runId}/manifest.json`, JSON.stringify(manifest))
        cloud.objects.set(`runs/${runId}/host/started`, '{}')

        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(2)

        expect([...cloud.objects.keys()].filter((key) => key.includes('/receipts/'))).toEqual([])
    })

    it('gives up within minutes on a host whose SSM agent never takes a command', async () => {
        const { controller } = prepare({ cloud: { agent: 'offline' } })
        let sentAt: number | undefined
        let deletedAt: number | undefined
        cloud.beforeCall('send-command', () => {
            sentAt ??= now.getTime()
        })
        cloud.beforeCall('delete-stack', () => {
            deletedAt ??= now.getTime()
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain('did not take the command')
        expect(deletedAt! - sentAt!).toBeLessThan(HOUR_MS / 12)
        expect(cloud.billable()).toEqual([])
    })

    it.each<[string, (fake: FakeCloud) => void]>([
        ['', () => undefined],
        [
            ', retrying a resource read that fails during teardown',
            (fake) => fake.failOnCall('describe-db-instances', 1),
        ],
        [
            ', judging an untyped tagged resource gone once its tag listing drops it',
            (fake) => fake.untyped.push('arn:aws:rds:us-east-1:000000000000:cluster-auto-backup:cab-0'),
        ],
        [', retrying a delete-stack that fails once', (fake) => fake.failOnCall('delete-stack')],
        [', listing the tagged resources again after a failed listing', (fake) => fake.failOnCall('get-resources', 2)],
        [
            ', keeping its host when the image parameter moves',
            (fake) => fake.beforeCall('update-stack', () => fake.parameterStore.set('/test/ubuntu/ami-id', 'ami-0b')),
        ],
    ])('creates the run stack, adds the reader, and leaves nothing billing%s', async (_, arrange) => {
        const { controller } = prepare()
        arrange(cloud)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

        const runId = leasedRunId()
        expect(cloud.resources.filter(({ type }) => type === 'AWS::EC2::Instance')).toHaveLength(1)
        expect(cloud.resources.map(({ type, id }) => `${type} ${id}`)).toContain(
            `AWS::RDS::DBInstance scn-${runId}-reader`
        )
        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
        expect(lastReceipt(runId)).toMatchObject({ runId, clean: true })
    })

    it.each([
        ['create-stack', 'fails', 1],
        ['create-stack', 'loses its response', 1],
        ['describe-stacks', 'fails', 1],
        ['update-stack', 'fails', 1],
        ['describe-stacks', 'fails', 3],
    ])('tears everything down when %s %s (call %d)', async (operation, how, nth) => {
        const { controller } = prepare()
        if (how === 'fails') {
            cloud.failOnCall(operation, nth)
        } else {
            cloud.loseResponseOf(operation, nth)
        }

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
        expect(released(leasedRunId())).toBe(1)
    })

    it.each<[string, Setup, string]>([
        ['the host writes its failed marker', { cloud: { host: 'failed' } }, 'host/bootstrap.log'],
        ['the host misses its bootstrap deadline', { cloud: { host: 'silent' } }, 'not ready within 30m'],
        ['the host halts before it can report', { cloud: { host: 'halted' } }, 'terminated before it reported'],
        [
            'the host stays silent until the lease expires',
            {
                cloud: { host: 'silent' },
                profile: (p) => ({ ...p, host: { ...p.host, bootstrapDeadline: '720m' } }),
            },
            'only its teardown allowance',
        ],
        ['the stack rolls back its creation', { cloud: { rollsBack: 'create' } }, 'not CREATE_COMPLETE'],
        [
            'the baseline denies a host from another launch template',
            { profile: (p) => ({ ...p, baseline: { ...p.baseline, hostLaunchTemplateId: 'lt-0000000000000000b' } }) },
            'not CREATE_COMPLETE',
        ],
        ['the stack rolls back the reader', { cloud: { rollsBack: 'update' } }, 'not UPDATE_COMPLETE'],
        ['the seed refuses its footprint', { cloud: { seed: { exitCode: 1 } } }, 'host/prepare.log'],
        ['the seed outlasts the lease', { cloud: { seed: { takesMs: 10 * HOUR_MS } } }, 'TimedOut'],
        ['the card outlasts the lease', { cloud: { card: { takesMs: 10 * HOUR_MS } } }, 'did not finish by'],
        [
            'the card reports an exit code the runner never uses',
            { cloud: { card: { exitCode: 7 } } },
            'without a runner exit',
        ],
        [
            'the card cannot upload its evidence',
            { cloud: { card: { uploadFails: true } } },
            'did not upload its evidence',
        ],
        [
            'the card dies without reporting done',
            { cloud: { card: { diesAfterMs: HOUR_MS / 2 } } },
            'stopped without reporting',
        ],
    ])('makes the run invalid and tears down when %s', async (_, setup, reason) => {
        const { controller } = prepare({ ...setup, env: { ...setup.env, ...api.credentials } })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(reason)
        expect(published()).toMatchObject({ run_id: leasedRunId(), origin: 'cloud-manual', status: 'invalid' })
        expect(published().status_reason).toContain(reason)
        expect(cloud.deleteStackRequests).toEqual([])
        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
    })

    it.each<[string, Partial<FakeCloudOptions>, number]>([
        ['passes', {}, 0],
        ['fails', { card: { exitCode: 1 } }, 1],
        ['cannot write its scorecard', { card: { exitCode: 3 } }, 3],
        ['passes while its liveness probes are lost', { probe: 'lost' }, 0],
        ['passes while its liveness probes time out', { probe: 'timedOut' }, 0],
    ])('seeds before it adds the reader, and exits as the card does when it %s', async (_, options, exitCode) => {
        const { controller } = prepare({ cloud: options, env: api.credentials })
        let doneAt: number | undefined
        let deletedAt: number | undefined
        onSleep = () => {
            if (doneAt === undefined && [...cloud.objects.keys()].some((key) => key.endsWith('/host/done'))) {
                doneAt = now.getTime()
            }
        }
        cloud.beforeCall('delete-stack', () => {
            deletedAt ??= now.getTime()
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(exitCode)

        const runId = leasedRunId()
        expect(deletedAt! - doneAt!).toBeLessThan(HOUR_MS / 6)
        expect(cloud.resources.find(({ logicalId }) => logicalId === 'Reader')).toMatchObject({ seeded: true })
        expect(parseJSON(cloud.objects.get(`runs/${runId}/host/done`)!)).toMatchObject({ exitCode })
        expect(cloud.objects.has(`runs/${runId}/evidence/SHA256SUMS`)).toBe(true)
        expect(cloud.billable()).toEqual([])
        expect(published()).toMatchObject({ run_id: runId, status: exitCode === 1 ? 'failed' : 'passed' })
    })

    it.each<[string, Partial<FakeCloudOptions>, (fake: FakeCloud) => void, boolean]>([
        ['it is interrupted while the card runs', {}, () => undefined, true],
        ['the card ignores the stop', { card: { ignoresStop: true } }, () => undefined, false],
        [
            'the card spends its whole fail-back budget cleaning up',
            { card: { stopTakesMs: FAILOVER_RELEASE_WITHIN_MS + 60_000 } },
            () => undefined,
            true,
        ],
        [
            'the card cleans up until just before systemd would kill it',
            { card: { stopTakesMs: STOP_TIMEOUT_S * 1000 - 1000 } },
            () => undefined,
            true,
        ],
        [
            'the stop command fails',
            {},
            (fake) => fake.failWhen('send-command', (args) => args.some((arg) => arg.includes('systemctl stop'))),
            false,
        ],
    ])('stops the card, then deletes the stack, when %s', async (_, options, arrange, uploaded) => {
        const { controller } = prepare({ cloud: options })
        arrange(cloud)
        let startedAt: number | undefined
        let interruptedAt: number | undefined
        let evidenceAtDelete: boolean | undefined
        let deletedAt: number | undefined
        onSleep = () => {
            if (startedAt === undefined && [...cloud.objects.keys()].some((key) => key.endsWith('/host/started'))) {
                startedAt = now.getTime()
            }
            if (interruptedAt === undefined && startedAt !== undefined && now.getTime() - startedAt >= HOUR_MS / 6) {
                interruptedAt = now.getTime()
                interrupt?.()
            }
        }
        cloud.beforeCall('delete-stack', () => {
            deletedAt ??= now.getTime()
            evidenceAtDelete ??= cloud.objects.has(`runs/${leasedRunId()}/evidence/SHA256SUMS`)
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(evidenceAtDelete).toBe(uploaded)
        expect(err.join('\n').includes('did not finish cleanly')).toBe(!uploaded)
        expect(deletedAt! - interruptedAt!).toBeLessThan(STOP_WAIT_MS + POLL_MS)
        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
    })

    it('tears down at once when interrupted while it waits for the host', async () => {
        const { controller } = prepare({ cloud: { host: 'silent' } })
        let interruptedAt: number | undefined
        let deletedAt: number | undefined
        onSleep = () => {
            const created = [...cloud.stacks.values()].some(({ status }) => status === 'CREATE_COMPLETE')
            if (created && interruptedAt === undefined) {
                interruptedAt = now.getTime()
                interrupt?.()
            }
        }
        cloud.beforeCall('delete-stack', () => {
            deletedAt ??= now.getTime()
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(deletedAt! - interruptedAt!).toBeLessThan(60_000)
        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
    })

    it.each<[string, string, () => boolean, number]>([
        ['as it resolves the host image', 'get-parameter', () => true, HOUR_MS / 6],
        ['as the host reports ready', 'list-objects-v2', () => true, HOUR_MS / 6],
    ])('creates nothing more when interrupted %s', async (_, operation, due, within) => {
        const { controller } = prepare()
        let createdBefore: number | undefined
        let interruptedAt: number | undefined
        cloud.beforeCall(operation, () => {
            if (interrupt && createdBefore === undefined && due()) {
                createdBefore = cloud.resources.length
                interruptedAt = now.getTime()
                interrupt()
            }
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(cloud.resources).toHaveLength(createdBefore!)
        expect(cloud.billable()).toEqual([])
        expect(now.getTime() - interruptedAt!).toBeLessThan(within)
    })

    it.each<[string, (interruptAt: (status: string) => () => void) => void]>([
        ['while the reader is added', (interruptAt) => (onSleep = interruptAt('UPDATE_IN_PROGRESS'))],
        [
            'as the reader update reports complete',
            (interruptAt) => cloud.beforeCall('describe-stacks', interruptAt('UPDATE_COMPLETE')),
        ],
    ])('tears down and exits invalid when interrupted %s', async (_, arrange) => {
        const { controller } = prepare()
        let interrupted = false
        arrange((status) => () => {
            if (!interrupted && [...cloud.stacks.values()].some((stack) => stack.status === status)) {
                interrupted = true
                interrupt?.()
            }
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
    })

    it.each<[string, string, () => boolean, string, boolean]>([
        ['create the stack after it reads the host image', 'get-parameter', () => true, 'too soon to create', false],
        ['seed the backlog', 'list-objects-v2', () => cloud.stacks.size > 0, 'too soon to seed the backlog', false],
        ['add the reader', 'get-command-invocation', () => true, 'too soon to add the reader', false],
        ['start the card', 'update-stack', () => true, 'too soon to start the card', true],
    ])('does not %s once the lease is too close to expiry', async (_, operation, ready, reason, readerAdded) => {
        const { controller } = prepare()
        let jumped = false
        cloud.beforeCall(operation, () => {
            if (!jumped && cloud.schedules.size === 2 && ready()) {
                jumped = true
                now = new Date(now.getTime() + 5.5 * HOUR_MS)
            }
        })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(reason)
        expect(cloud.resources.some(({ id }) => id.endsWith('-reader'))).toBe(readerAdded)
        expect([...cloud.objects.keys()].some((key) => key.endsWith('/host/started'))).toBe(false)
        expect(cloud.billable()).toEqual([])
    })

    it.each<[string, Partial<FakeCloudOptions>, (fake: FakeCloud) => void]>([
        ['the stack will not delete', { deleteFailures: 2 }, () => undefined],
        ['deleting the stack fails', {}, (fake) => fake.failOnCall('delete-stack', 1, Infinity)],
        [
            'deleting the stack fails before its creation reports back',
            {},
            (fake) => {
                fake.loseResponseOf('create-stack')
                fake.failOnCall('delete-stack', 1, Infinity)
            },
        ],
    ])('keeps the schedules and exits non-zero when %s, then cleanup finishes it', async (_, options, arrange) => {
        const { controller } = prepare({ cloud: options })
        arrange(cloud)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        const runId = leasedRunId()
        expect(cloud.billable()).not.toEqual([])
        expect(cloud.schedules.size).toBe(2)
        expect(err.join('\n')).toContain(`cleanup <cloud profile> ${runId}`)
        expect(lastReceipt(runId)).toMatchObject({ clean: false })

        cloud.heal()
        const cleanupStartedAt = now.getTime()
        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(0)

        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
        expect(now.getTime() - cleanupStartedAt).toBeLessThan(HOUR_MS / 6)
    })

    it.each<[string, (fake: FakeCloud) => void, string]>([
        ['it cannot list what the run created', (fake) => fake.failOnCall('get-resources', 1), 'could not list'],
        ['releasing the lease fails', (fake) => fake.failOnCall('delete-schedule', 2), 'releasing its lease failed'],
    ])('deletes the stack but keeps a schedule and names the cleanup when %s', async (_, arrange, reason) => {
        const { controller } = prepare()
        arrange(cloud)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        const runId = leasedRunId()
        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBeGreaterThan(0)
        expect(err.join('\n')).toContain(reason)
        expect(err.join('\n')).toContain(`cleanup <cloud profile> ${runId}`)

        cloud.heal()
        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(0)

        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
    })

    it.each<[string, string, (fake: FakeCloud) => void, (fake: FakeCloud) => void]>([
        ['AWS::EC2::Volume', '', () => undefined, () => undefined],
        ['AWS::SecretsManager::Secret', '', () => undefined, () => undefined],
        [
            'AWS::SecretsManager::Secret',
            ', even when listing the cluster snapshots fails',
            (fake) => fake.failOnCall('describe-db-cluster-snapshots', 1),
            () => undefined,
        ],
        [
            'AWS::SecretsManager::Secret',
            ', even when the run stops while the stack is created',
            (fake) => {
                onSleep = () => {
                    if (fake.resources.length > 0) {
                        interrupt?.()
                    }
                }
            },
            () => undefined,
        ],
        ['AWS::RDS::DBClusterAutomatedBackup', '', () => undefined, () => undefined],
        ['AWS::RDS::DBClusterSnapshot', '', () => undefined, () => undefined],
        [
            'AWS::RDS::DBClusterAutomatedBackup',
            ', even when the run cannot read the live cluster',
            (fake) => fake.failWhen('describe-db-clusters', () => fake.schedules.size > 0),
            (fake) => fake.heal(),
        ],
    ])('keeps the schedules and names a %s that outlives the stack%s', async (type, _, beforeRun, beforeCleanup) => {
        const { controller } = prepare({ cloud: { outlives: [type] } })
        beforeRun(cloud)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        const left = cloud.billable().filter((resource) => resource.startsWith(type))
        expect(left).toHaveLength(1)
        expect(err.join('\n')).toContain(`- ${left[0]}`)
        expect(cloud.schedules.size).toBe(2)

        beforeCleanup(cloud)
        await expect(main(['cleanup', profilePath(), leasedRunId()], controller)).resolves.toBe(2)
        await expect(main(['cleanup', profilePath(), leasedRunId()], controller)).resolves.toBe(2)

        expect(cloud.schedules.size).toBe(2)
    })

    it('changes nothing on a second cleanup of a torn-down run', async () => {
        const { controller } = prepare()
        await main(['run', profilePath(), FAILOVER_CARD], controller)
        const runId = leasedRunId()
        const resources = structuredClone(cloud.resources)

        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(0)

        expect(cloud.resources).toEqual(resources)
        expect(cloud.stacks.size).toBe(0)
        expect(cloud.schedules.size).toBe(0)
    })

    it('stops a card the dead controller left running before cleanup deletes the stack', async () => {
        const { controller } = prepare()
        let cardStarted!: () => void
        const died = new Promise<void>((resolve) => (cardStarted = resolve))
        onSleep = () => {
            if ([...cloud.objects.keys()].some((key) => key.endsWith('/host/started'))) {
                cardStarted()
                return new Promise(() => undefined)
            }
        }
        void main(['run', profilePath(), FAILOVER_CARD], controller)
        await died
        onSleep = undefined
        const runId = leasedRunId()
        let evidenceAtDelete: boolean | undefined
        cloud.beforeCall('delete-stack', () => {
            evidenceAtDelete ??= cloud.objects.has(`runs/${runId}/evidence/SHA256SUMS`)
        })

        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(0)

        expect(evidenceAtDelete).toBe(true)
        expect(cloud.billable()).toEqual([])
    })

    it.each<[string, Partial<FakeCloudOptions>, (fake: FakeCloud) => void, string, string]>([
        [
            'an idle reader under the idle limit and a T0 minute above it',
            { readerAcu: IDLE_THEN_PROMOTED },
            () => undefined,
            'passed',
            '',
        ],
        [
            'an average-only minute before T0 at the reader minimum',
            {
                readerAcu: IDLE_THEN_PROMOTED.map((minute) => (minute.minute === -3 ? { minute: -3, avg: 1 } : minute)),
            },
            () => undefined,
            'passed',
            '',
        ],
        [
            'a minute after T0 whose maximum CloudWatch left out',
            {
                readerAcu: [...IDLE_THEN_PROMOTED, { minute: 3, avg: 9 }],
            },
            () => undefined,
            'passed',
            '',
        ],
        [
            'a complete minute before T0 above the idle limit',
            {
                readerAcu: [
                    ...minutes(-5, -3, 1, 1),
                    ...minutes(-2, -2, 3, 2.6),
                    ...minutes(-1, -1, 1, 1),
                    ...minutes(0, 0, 2.5, 1.4),
                    ...minutes(1, 2, 8, 6),
                ],
            },
            () => undefined,
            'invalid',
            'reader above its 2.5 ACU idle limit before T0',
        ],
        [
            'a minute before T0 above the idle limit whose average CloudWatch left out',
            {
                readerAcu: [
                    ...minutes(-5, -3, 1, 1),
                    { minute: -2, max: 3 },
                    ...minutes(-1, -1, 1, 1),
                    ...minutes(0, 0, 2.5, 1.4),
                    ...minutes(1, 2, 8, 6),
                ],
            },
            () => undefined,
            'invalid',
            'reader above its 2.5 ACU idle limit before T0',
        ],
        [
            'a minute before T0 under the idle limit whose maximum CloudWatch left out',
            {
                readerAcu: [
                    ...minutes(-5, -3, 1, 1),
                    { minute: -2, avg: 2 },
                    ...minutes(-1, -1, 1, 1),
                    ...minutes(0, 0, 2.5, 1.4),
                    ...minutes(1, 2, 8, 6),
                ],
            },
            () => undefined,
            'invalid',
            'no reader maximum before T0 to show the reader under its 2.5 ACU idle limit',
        ],
        [
            'a minute before T0 below the reader minimum whose maximum CloudWatch left out',
            {
                readerAcu: [
                    ...minutes(-5, -3, 1, 1),
                    { minute: -2, avg: 0.5 },
                    ...minutes(-1, -1, 1, 1),
                    ...minutes(0, 0, 2.5, 1.4),
                    ...minutes(1, 2, 8, 6),
                ],
            },
            () => undefined,
            'invalid',
            'no reader maximum before T0 to show the reader under its 2.5 ACU idle limit',
        ],
        [
            'a minute before T0 above the idle limit whose maximum CloudWatch left out',
            {
                readerAcu: [
                    ...minutes(-5, -3, 1, 1),
                    { minute: -2, avg: 3 },
                    ...minutes(-1, -1, 1, 1),
                    ...minutes(0, 0, 2.5, 1.4),
                    ...minutes(1, 2, 8, 6),
                ],
            },
            () => undefined,
            'invalid',
            'reader above its 2.5 ACU idle limit before T0',
        ],
        [
            'no capacity for the minute before T0',
            { readerAcu: IDLE_THEN_PROMOTED.filter(({ minute }) => minute !== -1) },
            () => undefined,
            'invalid',
            'no reader maximum for the minute before T0',
        ],
        [
            'a CloudWatch series with fewer values than timestamps',
            { readerAcu: IDLE_THEN_PROMOTED, shortValuesOf: 'Average' },
            () => undefined,
            'invalid',
            'could not read the reader capacity',
        ],
        [
            'a CloudWatch timestamp that is not a time',
            { readerAcu: IDLE_THEN_PROMOTED, unknownTimestampOf: 'Average' },
            () => undefined,
            'invalid',
            'could not read the reader capacity',
        ],
        [
            'the oldest of the five minutes before T0 missing',
            { readerAcu: IDLE_THEN_PROMOTED.filter(({ minute }) => minute !== -5) },
            () => undefined,
            'invalid',
            'no reader capacity in the 5 minutes before T0 for',
        ],
        [
            'a whole minute missing from the five before T0',
            { readerAcu: IDLE_THEN_PROMOTED.filter(({ minute }) => minute !== -2) },
            () => undefined,
            'invalid',
            'no reader capacity in the 5 minutes before T0 for',
        ],
        [
            'a series that ends before T0',
            { readerAcu: minutes(-3, -1, 1, 1) },
            () => undefined,
            'invalid',
            'no measured reader maximum from T0 on',
        ],
        [
            'no capacity before T0',
            { readerAcu: [...minutes(0, 0, 2.5, 1.4), ...minutes(1, 2, 8, 6)] },
            () => undefined,
            'invalid',
            'no reader capacity before T0',
        ],
        [
            'capacity CloudWatch cannot answer',
            { readerAcu: minutes(-3, 2, 1, 1) },
            (fake) => fake.failWhen('get-metric-data', (args) => args.includes('--scan-by')),
            'invalid',
            'could not read the reader capacity',
        ],
        [
            'an average above the idle limit in a minute whose maximum is under it',
            {
                readerAcu: IDLE_THEN_PROMOTED.map((minute) =>
                    minute.minute === -2 ? { ...minute, max: 2, avg: 3 } : minute
                ),
            },
            () => undefined,
            'invalid',
            'reader above its 2.5 ACU idle limit before T0',
        ],
        [
            'a maximum before T0 under the reader minimum',
            {
                readerAcu: IDLE_THEN_PROMOTED.map((minute) =>
                    minute.minute === -3 ? { ...minute, max: 0, avg: 0 } : minute
                ),
            },
            () => undefined,
            'invalid',
            'reader capacity under its 1 ACU minimum before T0',
        ],
        [
            'an average before T0 under the reader minimum',
            {
                readerAcu: IDLE_THEN_PROMOTED.map((minute) =>
                    minute.minute === -3 ? { ...minute, avg: 0.5 } : minute
                ),
            },
            () => undefined,
            'invalid',
            'reader capacity under its 1 ACU minimum before T0',
        ],
        [
            'an average before T0 above its maximum, both under the idle limit',
            {
                readerAcu: IDLE_THEN_PROMOTED.map((minute) =>
                    minute.minute === -3 ? { ...minute, avg: 1.2 } : minute
                ),
            },
            () => undefined,
            'invalid',
            'reader average above its maximum before T0',
        ],
        [
            'a reader above the idle limit while the failover waits for its offset',
            {
                readerAcu: [
                    ...minutes(-12, -11, 1, 1),
                    { minute: -10, max: 3, avg: 2 },
                    ...minutes(-9, -1, 1, 1),
                    ...minutes(0, 0, 2.5, 1.4),
                    ...minutes(1, 2, 8, 6),
                ],
            },
            () => undefined,
            'invalid',
            'reader above its 2.5 ACU idle limit before T0',
        ],
        [
            'a failover entry without the instant of its request',
            { card: { journalsIntent: false } },
            () => undefined,
            'invalid',
            'the runner recorded no pg.failover request',
        ],
        [
            'CloudWatch refusing the average series',
            { averageStatuses: ['Forbidden'] },
            () => undefined,
            'invalid',
            "CloudWatch's avg series came back Forbidden, not Complete",
        ],
        [
            'a card that passes before its failover',
            { card: { takesMs: HOUR_MS / 6 } },
            () => undefined,
            'invalid',
            'the runner recorded no pg.failover',
        ],
        [
            'a runner status outside passed, failed and invalid',
            { card: { runnerStatus: 'skipped' } },
            () => undefined,
            'invalid',
            'could not read the runner scorecard',
        ],
        [
            'a passed scorecard from a runner that then exited invalid',
            { card: { exitCode: 2, runnerStatus: 'passed' } },
            () => undefined,
            'invalid',
            'the runner exited 2 after it saved a passed scorecard',
        ],
    ])('judges the run on %s and publishes it', async (_, cloudOptions, arrange, status, reason) => {
        const { controller } = prepare({ cloud: cloudOptions, env: api.credentials })
        arrange(cloud)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(status === 'passed' ? 0 : 2)

        expect(published()).toMatchObject({ run_id: leasedRunId(), status })
        expect(published().status_reason).toContain(reason)
        if (status === 'passed') {
            expect(published()).toMatchObject({
                acu_pre_t0_max: 2,
                acu_t0_minute_max: 4,
                acu_peak: 8,
                acu_seconds_to_peak: 60,
                reader_acu_at_t0: 1.5,
            })
            const t0 = Date.parse(String(published().t0_at))
            expect(published().acu_gaps).not.toContain(new Date(t0 - (t0 % 60_000)).toISOString())
            expect(out).toContain(`The reader sat at 1.5 ACU in the minute before T0 (${published().t0_at}).`)
        }
    })

    it.each<[string, number, number, string, string]>([
        [
            'under the highest reader maximum before T0',
            1.5,
            2,
            'invalid',
            'reader above its 1.5 ACU idle limit before T0',
        ],
        ['at the highest reader maximum before T0', 2, 0, 'passed', ''],
    ])(
        'judges the reader against an idle limit its own profile sets %s',
        async (_, idleMax, exitCode, status, reason) => {
            const { controller } = prepare({
                profile: (p) => ({ ...p, readerAcu: { ...p.readerAcu, idleMax } }),
                cloud: { readerAcu: IDLE_THEN_PROMOTED },
                env: api.credentials,
            })

            await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(exitCode)

            expect(published()).toMatchObject({ status, reader_acu_at_t0: 1.5 })
            expect(published().status_reason).toContain(reason)
        }
    )

    it.each<[string, Partial<FakeCloudOptions>, string, string]>([
        [
            'CloudWatch refuses only the average series',
            { readerAcu: IDLE_THEN_PROMOTED, averageStatuses: ['Forbidden'] },
            'Could not read the reader capacity, so its ACU in the minute before T0',
            'could not read the reader capacity',
        ],
        [
            'CloudWatch has an average at the reader minimum but no maximum for the minute before T0',
            {
                readerAcu: IDLE_THEN_PROMOTED.map((minute) => (minute.minute === -1 ? { minute: -1, avg: 1 } : minute)),
            },
            'CloudWatch has no reader maximum for the minute before T0',
            'no reader maximum for the minute before T0',
        ],
    ])('names what is missing when %s', async (_, cloudOptions, summary, reason) => {
        const { controller } = prepare({ cloud: cloudOptions, env: api.credentials })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        expect(out.join('\n')).toContain(summary)
        expect(published()).toMatchObject({ status: 'invalid', reader_acu_at_t0: null })
        expect(published().status_reason).toContain(reason)
    })

    it('publishes the receipt, the cost estimate and the fingerprint beside the runner measurements', async () => {
        const readerAcu: ReaderMinute[] = [
            ...minutes(-30, -1, 1, 1),
            ...minutes(0, 9, 6, 5),
            ...minutes(12, 29, 6, 5),
            { minute: 30, max: 6 },
        ]
        const { controller } = prepare({ cloud: { readerAcu }, env: api.credentials })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

        const runId = leasedRunId()
        const { createdAt } = parseJSON(cloud.objects.get(`runs/${runId}/manifest.json`)!) as { createdAt: string }
        const properties = published()
        const hours = (Date.parse(String(properties.ended_at)) - Date.parse(createdAt)) / HOUR_MS
        const t0 = Date.parse(String(properties.t0_at))
        const minuteAt = (offset: number): string => new Date(t0 - (t0 % 60_000) + offset * 60_000).toISOString()
        const cardEndOffset = Math.floor((cardOf(runId).endedAt - (t0 - (t0 % 60_000))) / 60_000)
        const gapOffsets = [10, 11, ...Array.from({ length: cardEndOffset - 29 }, (_, i) => 30 + i)]
        expect(properties).toMatchObject({
            run_id: runId,
            origin: 'cloud-manual',
            target: 'cloud',
            started_at: createdAt,
            status: 'passed',
            m_writer_recovery_s: 42,
            environment_kind: 'run-host',
            writer_class: 'db.r8g.2xlarge',
            reader_acu_min: 1,
            reader_acu_max: 32,
            reader_acu_idle_max: 2.5,
            reader_monitoring_interval_seconds: 60,
            host_class: 'm7i.8xlarge',
            engine_version: '16.4',
            pooler_replicas: 2,
            cloud_profile_hash: sha256(readFileSync(profilePath(), 'utf8')),
            runner_profile_hash: sha256(readFileSync(path.join(dir, 'runner.yaml'), 'utf8')),
            teardown_clean: true,
            teardown_leftovers: [],
            acu_gaps: gapOffsets.map(minuteAt),
            cost_estimate_excluded: ['data transfer', 'S3 requests', 'Enhanced Monitoring log ingestion'],
        })
        expect(properties.deviations).toEqual(expect.arrayContaining([expect.stringMatching(/team skew/)]))
        expect(properties.cost_estimate_items).toEqual(
            expect.arrayContaining([
                `writer db.r8g.2xlarge, ${hours.toFixed(2)} h: $${hours.toFixed(2)}`,
                `reader, 2.83 ACU-hours, ${gapOffsets.length} minutes missing: $0.28`,
            ])
        )
        const items = properties.cost_estimate_items as string[]
        const total = items.reduce((sum, item) => sum + Number(/\$(\d+\.\d\d)$/.exec(item)![1]), 0)
        expect(properties.cost_estimate_usd).toBeCloseTo(total, 1)
        expect(parseJSON(cloud.objects.get(`runs/${runId}/scorecard.json`)!)).toEqual(properties)
    })

    it('counts every minute of the card as missing when CloudWatch returns no reader capacity', async () => {
        const { controller } = prepare({ cloud: { readerAcu: [] }, env: api.credentials })

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        const { startedAt, endedAt } = cardOf(leasedRunId())
        const minuteIso = (at: number): string => new Date(at - (at % 60_000)).toISOString()
        const gaps = published().acu_gaps as string[]
        const cardMinutes = (Date.parse(minuteIso(endedAt)) - Date.parse(minuteIso(startedAt))) / 60_000 + 1
        expect(gaps).toEqual(
            Array.from({ length: cardMinutes }, (_, i) =>
                new Date(Date.parse(minuteIso(startedAt)) + i * 60_000).toISOString()
            )
        )
        expect(published().cost_estimate_items).toContainEqual(
            expect.stringContaining(`reader, 0.00 ACU-hours, ${gaps.length} minutes missing`)
        )
    })

    it('fingerprints runs alike only when their environment matches', async () => {
        const fingerprintOf = async (profile: Setup['profile']): Promise<unknown> => {
            api.captured.length = 0
            const { controller } = prepare({ profile, env: api.credentials })
            await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)
            return published().fingerprint
        }

        const first = await fingerprintOf((p) => p)
        const repriced = await fingerprintOf((p) => ({
            ...p,
            admission: { ...p.admission, rates: { ...p.admission.rates, hostPerHour: 2 } },
        }))
        const other = await fingerprintOf((p) => ({
            ...p,
            pooler: { ...p.pooler, settings: { ...p.pooler.settings, default_pool_size: 40 } },
        }))
        const monitoredEverySecond = await fingerprintOf((p) => ({ ...p, readerMonitoringIntervalSeconds: 1 }))
        const monitoredEveryFiveSeconds = await fingerprintOf((p) => ({ ...p, readerMonitoringIntervalSeconds: 5 }))
        const monitoredEveryFiveSecondsAgain = await fingerprintOf((p) => ({
            ...p,
            readerMonitoringIntervalSeconds: 5,
        }))
        const lowerIdleLimit = await fingerprintOf((p) => ({ ...p, readerAcu: { ...p.readerAcu, idleMax: 2 } }))

        expect(first).toMatch(/^[0-9a-f]{64}$/)
        expect(repriced).toBe(first)
        expect(other).not.toBe(first)
        expect(monitoredEverySecond).not.toBe(first)
        expect(monitoredEveryFiveSeconds).not.toBe(monitoredEverySecond)
        expect(monitoredEveryFiveSecondsAgain).toBe(monitoredEveryFiveSeconds)
        expect(lowerIdleLimit).not.toBe(first)
    })

    it.each<[string, Setup['profile']]>([
        ['without an idle limit', ({ readerAcu: { idleMax: _, ...readerAcu }, ...p }) => ({ ...p, readerAcu })],
        ['with an idle limit', (p) => p],
    ])('keeps the fingerprint of a scale run under a profile %s', async (_, profile) => {
        const { controller } = prepare({ profile, env: api.credentials })

        await main(['run', profilePath(), 'cyclotron-scale'], controller)

        expect(published().fingerprint).toBe('2065d69326248cfa85df8346e4b82628228fe78b97b2e9fcacf8edfdcc65aa94')
    })

    it.each<[string, (fake: FakeCloud) => void, (volumeId: string) => unknown]>([
        ['its receipt lists', () => undefined, (volumeId) => [expect.stringContaining(volumeId)]],
        [
            'an unreadable receipt reports as unknown',
            (fake) => fake.failWhen('get-object', (args) => args.some((arg) => arg.includes('/receipts/'))),
            () => [expect.stringMatching(/^unknown: the teardown receipt could not be read/)],
        ],
        [
            'a receipt teardown could not save reports as unknown',
            (fake) => fake.failWhen('put-object', (args) => args.some((arg) => arg.includes('/receipts/'))),
            () => [expect.stringMatching(/^unknown: teardown saved no receipt/)],
        ],
        [
            'a listing teardown could not finish reports as unknown',
            (fake) => fake.failOnCall('get-resources', 1),
            () => expect.arrayContaining([expect.stringMatching(/^unknown: could not list /)]),
        ],
    ])('publishes an invalid run with what teardown left behind, which %s', async (_, arrange, leftovers) => {
        const { controller } = prepare({ cloud: { outlives: ['AWS::EC2::Volume'] }, env: api.credentials })
        arrange(cloud)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(2)

        const [volume] = cloud.billable()
        expect(published()).toMatchObject({ status: 'invalid', teardown_clean: false })
        expect(published().teardown_leftovers).toEqual(leftovers(volume.split(' ')[1]))
    })

    it.each<[string, Partial<FakeCloudOptions>, boolean, (fake: FakeCloud) => void]>([
        [
            'Scenario runs refuses the scorecard of an invalid run',
            { outlives: ['AWS::EC2::Volume'] },
            true,
            () => undefined,
        ],
        [
            'the bucket refuses the copy and no Scenario runs credentials are set',
            {},
            false,
            (fake) =>
                fake.failWhen('put-object', (args) => args.some((arg) => /^runs\/[^/]+\/scorecard\.json$/.test(arg))),
        ],
    ])('exits as a failed scorecard write when %s', async (_, cloudOptions, refused, arrange) => {
        const env = refused ? { ...api.credentials, SCENARIO_RUNS_PROJECT_TOKEN: 'wrong' } : {}
        const { controller } = prepare({ cloud: cloudOptions, env })
        arrange(cloud)

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(3)

        expect(api.captured).toEqual([])
    })

    it('keeps the scorecard in the bucket and names it when no Scenario runs credentials are set', async () => {
        const { controller } = prepare()

        await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

        const key = `runs/${leasedRunId()}/scorecard.json`
        expect(parseJSON(cloud.objects.get(key)!)).toMatchObject({ origin: 'cloud-manual', status: 'passed' })
        expect(out.join('\n')).toContain(`s3://test-evidence/${key}`)
        expect(api.captured).toEqual([])
    })

    describe('reporting to the run store', () => {
        let store: TestStore

        beforeAll(async () => {
            store = await startTestStore('cloud')
        })

        afterAll(() => store.close())

        it('stores the scorecard it publishes as a Workflows run', async () => {
            const { controller } = prepare({ env: { ...api.credentials, ...store.envOf(dir) } })

            await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

            expect(await store.read(leasedRunId())).toMatchObject({
                scorecard: published(),
                adapters: ['workflows'],
                owners: [],
                target: 'cloud',
            })
            expect(out).toContain('Reported the run to the run store.')
        })

        it.each<[string, (home: string) => NodeJS.ProcessEnv, RegExp]>([
            ['the run store is down', (home) => storeEnvOf(home, UNREACHABLE_STORE), /the run store did not answer/],
            [
                'the run token cannot be read',
                (home) => {
                    const env = storeEnvOf(home, UNREACHABLE_STORE)
                    const tokenPath = storeTokenPathOf(env)
                    rmSync(tokenPath)
                    mkdirSync(tokenPath)
                    return env
                },
                /the run token could not be read: EISDIR/,
            ],
        ])('keeps its exit code and warns when %s', async (_story, envOf, said) => {
            const { controller } = prepare({ env: envOf(dir) })

            await expect(main(['run', profilePath(), FAILOVER_CARD], controller)).resolves.toBe(0)

            expect(err.join('\n')).toMatch(new RegExp(`Could not report the run to the run store: ${said.source}`))
        })
    })

    it('deletes the stack by schedule when the controller dies after creating it', async () => {
        const { controller } = prepare({ cloud: { host: 'silent' } })
        let waitingForHost!: () => void
        const died = new Promise<void>((resolve) => (waitingForHost = resolve))
        onSleep = () => {
            waitingForHost()
            return new Promise(() => undefined)
        }
        void main(['run', profilePath(), FAILOVER_CARD], controller)
        await died
        const runId = leasedRunId()
        expect(cloud.billable()).not.toEqual([])

        now = new Date(T.getTime() + 6 * HOUR_MS + 60_000)
        cloud.tick()

        expect(cloud.deleteStackRequests).toEqual([{ stackName: `scn-${runId}`, at: '2026-03-02T16:00:00.000Z' }])
        expect(cloud.billable()).toEqual([])
    })
})
