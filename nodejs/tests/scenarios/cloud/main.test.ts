import { createHash } from 'crypto'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

import { parseJSON } from '~/common/utils/json-parse'

import { FakeCloud, FakeCloudOptions } from './fake-cloud'
import { lease } from './lease'
import { Controller, main } from './main'
import { loadRunInputs } from './profile'

const T = new Date('2026-03-02T10:00:00.000Z')
const HOUR_MS = 60 * 60 * 1000
const COMMIT = 'c0ffee0000000000000000000000000000000000'
const OWNER = 'arn:aws:sts::000000000000:assumed-role/scenario-run-controller/person'
const OTHER_ACCOUNT = '111111111111'

const PROFILE = {
    name: 'test-eu',
    account: '000000000000',
    region: 'us-east-1',
    availabilityZone: 'us-east-1a',
    baseline: {
        schedulerRole: 'arn:aws:iam::000000000000:role/test-scheduler',
        stackServiceRole: 'arn:aws:iam::000000000000:role/test-stacks',
        monitoringRole: 'arn:aws:iam::000000000000:role/test-monitoring',
        evidenceBucket: 'test-evidence',
        dbSubnetGroup: 'test-db-subnets',
        databaseSecurityGroup: 'sg-0000000000000000a',
        clusterParameterGroup: 'test-cluster-parameters',
        instanceParameterGroup: 'test-instance-parameters',
        hostSubnet: 'subnet-0000000000000000a',
        hostSecurityGroup: 'sg-0000000000000000b',
        hostInstanceProfile: 'test-host',
    },
    engineVersion: '16.4',
    writerClass: 'db.r8g.2xlarge',
    readerAcu: { min: 1, max: 32 },
    host: {
        class: 'm7i.8xlarge',
        ebsGb: 100,
        imageParameter: '/test/ubuntu/ami-id',
        bootstrapDeadline: '30m',
    },
    runnerProfile: 'runner.yaml',
    admission: {
        teardownAllowance: '60m',
        priceList: {
            version: '20260101000000',
            feeds: [{ url: 'https://pricing.example.com/rds.json', sha256: 'a'.repeat(64) }],
        },
        rates: {
            writerPerHour: 1,
            acuPerHour: 0.1,
            hostPerHour: 1,
            storagePerGbMonth: 0.2,
            ebsPerGbMonth: 0.1,
            logsIngestPerGb: 0.5,
            transferPerGb: 0.1,
            s3PerThousandRequests: 0.01,
        },
        allowances: { storageGb: 73, transferGb: 10, s3Requests: 10_000, enhancedMonitoringEventBytes: 10_000 },
        reserve: { marginUsd: 10 },
    },
}

type Setup = {
    profile?: (profile: typeof PROFILE) => unknown
    cloud?: Partial<FakeCloudOptions>
    published?: boolean
    ssoToken?: Record<string, Date | string>
    env?: NodeJS.ProcessEnv
    arrange?: (cloud: FakeCloud) => void
}

const sha256 = (text: string): string => createHash('sha256').update(text).digest('hex')

describe('cloud controller', () => {
    let dir: string
    let now: Date
    let cloud: FakeCloud
    let out: string[]
    let err: string[]
    let interrupt: (() => void) | undefined
    let onSleep: (() => Promise<void> | void) | undefined

    const profilePath = (): string => path.join(dir, 'profile.yaml')

    function prepare({
        profile = (p) => p,
        cloud: options = {},
        published = true,
        ssoToken,
        env = {},
        arrange = () => undefined,
    }: Setup = {}): {
        controller: Controller
    } {
        writeFileSync(profilePath(), stringify(profile(structuredClone(PROFILE))))
        writeFileSync(path.join(dir, 'runner.yaml'), stringify({ name: 'test-current', traffic: {}, settings: {} }))
        cloud = new FakeCloud({ now: () => now, expiration: new Date(T.getTime() + 12 * HOUR_MS), ...options })
        arrange(cloud)
        if (ssoToken) {
            const cache = path.join(dir, '.aws', 'sso', 'cache')
            mkdirSync(cache, { recursive: true })
            const name = createHash('sha1').update(cloud.ssoSession!).digest('hex')
            writeFileSync(
                path.join(cache, `${name}.json`),
                JSON.stringify(
                    Object.fromEntries(
                        Object.entries(ssoToken).map(([key, value]) => [
                            key,
                            value instanceof Date ? value.toISOString() : value,
                        ])
                    )
                )
            )
        }
        const controller: Controller = {
            aws: cloud,
            origin: { head: () => COMMIT, published: (commit) => Promise.resolve(published && commit === COMMIT) },
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
        const manifest = await lease(controller, loadRunInputs(profilePath()), { owner: OWNER, commit: COMMIT })
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

    const listsReceipts = (args: string[]): boolean => args.some((arg) => arg.includes('/receipts/'))

    const released = (runId: string): number => out.filter((line) => line === `Released run ${runId}.`).length

    const schedulesFor = (runId: string): string[] =>
        [...cloud.schedules.values()]
            .filter(({ target }) => target.Input.includes(runId))
            .map(({ expression }) => expression)
            .sort()

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-cloud-'))
        now = T
        out = []
        err = []
        interrupt = undefined
        onSleep = undefined
    })

    afterEach(() => rmSync(dir, { recursive: true, force: true }))

    it.each([
        ['60m', '$47.99', /teardown tail.*\$5\.27/],
        ['120m', '$53.26', /teardown tail.*\$10\.54/],
    ])(
        'prints the itemized worst-case estimate for the fixed six-hour TTL, with a %s teardown allowance',
        async (allowance, total, tail) => {
            const { controller } = prepare({
                profile: (p) => ({ ...p, admission: { ...p.admission, teardownAllowance: allowance } }),
            })

            await expect(main(['run', profilePath()], controller)).resolves.toBe(0)

            expect(out.join('\n')).toContain(`Admitted estimate: ${total} of the $200 cap`)
            expect(out.join('\n')).toMatch(/reader at 32 ACU.*\$19\.20/)
            expect(out.join('\n')).toMatch(tail)
        }
    )

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
        expect(manifest).toMatchObject({ runId, owner: OWNER, commit: COMMIT, expiresAt: '2026-03-02T16:00:00.000Z' })
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

    it('releases the lease when the run ends', async () => {
        const { controller } = prepare()

        await expect(main(['run', profilePath()], controller)).resolves.toBe(0)
        now = new Date(T.getTime() + 7 * HOUR_MS)
        await expect(main(['cleanup', profilePath(), '--expired'], controller)).resolves.toBe(0)

        const runId = leasedRunId()
        expect(released(runId)).toBe(1)
        expect(cloud.schedules.size).toBe(0)
        expect(cloud.deleteStackRequests).toEqual([])
    })

    it('admits a refreshable SSO session and warns that the schedules bound it', async () => {
        const { controller } = prepare({
            cloud: { ssoSession: 'test-sso' },
            ssoToken: {
                expiresAt: new Date(T.getTime() + HOUR_MS),
                refreshToken: 'example-refresh',
                clientId: 'example-client',
                clientSecret: 'example-secret',
                registrationExpiresAt: new Date(T.getTime() + 90 * 24 * HOUR_MS),
            },
        })

        await expect(main(['run', profilePath()], controller)).resolves.toBe(0)

        expect(err.join('\n')).toContain('stack-delete schedules')
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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(0)

        const manifest = parseJSON(cloud.objects.get(`runs/${leasedRunId()}/input/manifest.json`)!)
        expect(manifest.account).toEqual(PROFILE.account)
    })

    it('reads the profile inputs once, so the uploads match the admitted hashes', async () => {
        const { controller } = prepare()
        const published = controller.origin.published
        controller.origin.published = (commit) => {
            writeFileSync(path.join(dir, 'runner.yaml'), 'edited: during admission\n')
            return published(commit)
        }

        await expect(main(['run', profilePath()], controller)).resolves.toBe(0)

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
        [
            'role credentials that expire first',
            { cloud: { expiration: new Date(T.getTime() + 2 * HOUR_MS) } },
            'expire',
        ],
        [
            'an SSO token that expires before its role credentials',
            { cloud: { ssoSession: 'test-sso' }, ssoToken: { expiresAt: new Date(T.getTime() + 2 * HOUR_MS) } },
            'expire',
        ],
        [
            'a controller role profile whose SSO session expires first',
            {
                cloud: { ssoSession: 'test-sso', sourceProfile: 'dev-write' },
                ssoToken: { expiresAt: new Date(T.getTime() + 2 * HOUR_MS) },
            },
            'expire',
        ],
        ['an SSO session with no cached token', { cloud: { ssoSession: 'test-sso' } }, 'aws sso login'],
        [
            'an SSO refresh token whose client registration ends before the run',
            {
                cloud: { ssoSession: 'test-sso' },
                ssoToken: {
                    expiresAt: new Date(T.getTime() + HOUR_MS),
                    refreshToken: 'example-refresh',
                    clientId: 'example-client',
                    clientSecret: 'example-secret',
                    registrationExpiresAt: new Date(T.getTime() + 2 * HOUR_MS),
                },
            },
            'expire',
        ],
        [
            'an SSO refresh token without its client id',
            {
                cloud: { ssoSession: 'test-sso' },
                ssoToken: {
                    expiresAt: new Date(T.getTime() + HOUR_MS),
                    refreshToken: 'example-refresh',
                    clientSecret: 'example-secret',
                    registrationExpiresAt: new Date(T.getTime() + 90 * 24 * HOUR_MS),
                },
            },
            'expire',
        ],
        [
            'an SSO refresh token without its client secret',
            {
                cloud: { ssoSession: 'test-sso' },
                ssoToken: {
                    expiresAt: new Date(T.getTime() + HOUR_MS),
                    refreshToken: 'example-refresh',
                    clientId: 'example-client',
                    registrationExpiresAt: new Date(T.getTime() + 90 * 24 * HOUR_MS),
                },
            },
            'expire',
        ],
        [
            'web identity credentials with no expiry, over an SSO profile',
            {
                cloud: { ssoSession: 'test-sso', expiration: null },
                ssoToken: { expiresAt: new Date(T.getTime() + 24 * HOUR_MS) },
                env: { AWS_WEB_IDENTITY_TOKEN_FILE: '/var/run/example-token' },
            },
            'expiry',
        ],
        [
            'a permission probe that fails for a reason other than access',
            { arrange: (fake) => fake.failOnCall('get-schedule') },
            'Could not check permission scheduler:GetSchedule',
        ],
        [
            'environment credentials with no expiry, over an SSO profile',
            {
                cloud: { ssoSession: 'test-sso', expiration: null },
                ssoToken: { expiresAt: new Date(T.getTime() + 24 * HOUR_MS) },
                env: { AWS_ACCESS_KEY_ID: 'AKIAEXAMPLE' },
            },
            'expiry',
        ],
        ['credentials with no known expiry', { cloud: { expiration: null } }, 'expiry'],
        ['role credentials with an unreadable expiry', { cloud: { expiration: 'not a date' } }, 'unreadable expiry'],
        [
            'an SSO token with an unreadable expiry',
            { cloud: { ssoSession: 'test-sso' }, ssoToken: { expiresAt: 'not a date' } },
            'unreadable expiry',
        ],
        ['a commit that is not on origin', { published: false }, COMMIT],
        ['a writer class that is not orderable', { cloud: { orderable: ['db.serverless'] } }, 'db.r8g.2xlarge'],
        [
            'a missing permission',
            { cloud: { denied: ['logs:FilterLogEvents'] } },
            'Missing permission logs:FilterLogEvents',
        ],
        [
            'a missing permission that teardown needs to judge a volume',
            { cloud: { denied: ['ec2:DescribeVolumes'] } },
            'Missing permission ec2:DescribeVolumes',
        ],
        [
            'a missing permission that teardown needs to judge a database instance',
            { cloud: { denied: ['rds:DescribeDBInstances'] } },
            'Missing permission rds:DescribeDBInstances',
        ],
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
    ])('refuses %s before it writes anything', async (_, setup, reason) => {
        const { controller } = prepare(setup)

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(reason)
        expect(cloud.objects.size).toBe(0)
        expect(cloud.schedules.size).toBe(0)
    })

    const PERSON_ROLE = 'AWSReservedSSO_administrators_0123456789abcdef'

    const CONTROLLER = 'the scenario-run-controller role'
    const MISMATCH = `account ${OTHER_ACCOUNT}, and the profile names 222222222222`

    it.each<[string, string, string, string, string, (runId: string) => string[]]>([
        ['run', PERSON_ROLE, 'person', OTHER_ACCOUNT, CONTROLLER, () => ['run', profilePath()]],
        [
            'cleanup --expired',
            PERSON_ROLE,
            'person',
            OTHER_ACCOUNT,
            CONTROLLER,
            () => ['cleanup', profilePath(), '--expired'],
        ],
        [
            'cleanup <run id>',
            PERSON_ROLE,
            'person',
            OTHER_ACCOUNT,
            CONTROLLER,
            (runId) => ['cleanup', profilePath(), runId],
        ],
        ['run', 'scenario-run-controller-copy', 'person', OTHER_ACCOUNT, CONTROLLER, () => ['run', profilePath()]],
        ['run', PERSON_ROLE, 'scenario-run-controller', OTHER_ACCOUNT, CONTROLLER, () => ['run', profilePath()]],
        [
            'cleanup --expired',
            'scenario-run-controller',
            'person',
            '222222222222',
            MISMATCH,
            () => ['cleanup', profilePath(), '--expired'],
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

    it('prints the estimate when it refuses a run over the cap', async () => {
        const { controller } = prepare({
            profile: (p) => ({
                ...p,
                admission: { ...p.admission, rates: { ...p.admission.rates, writerPerHour: 30 } },
            }),
        })

        await main(['run', profilePath()], controller)

        expect(out.join('\n')).toContain('Admitted estimate: $250.99 of the $200 cap')
    })

    it.each([
        ['an input upload', 'put-object', 4],
        ['the second schedule', 'create-schedule', 2],
        ['a schedule read-back', 'get-schedule', 2],
    ])('refuses and removes the partial lease when %s fails', async (_, operation, nth) => {
        const { controller } = prepare()
        cloud.failOnCall(operation, nth)

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain('Could not lease')
        expect(cloud.objects.size).toBe(0)
        expect(cloud.schedules.size).toBe(0)
    })

    it('still removes the uploaded inputs when removing a schedule fails, and names what remains', async () => {
        const { controller } = prepare()
        cloud.failOnCall('create-schedule', 2)
        cloud.failOnCall('delete-schedule', 1)

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(cloud.objects.size).toBe(0)
        const [left] = [...cloud.schedules.keys()]
        const leftLine = err
            .join('\n')
            .split('\n')
            .find((line) => line.startsWith(`- schedule ${left}`))
        expect(leftLine).toContain('DeleteSchedule operation')
        expect(err.join('\n')).toContain(left.replace(/^scn-(.+)-expiry$/, '$1'))
    })

    it('cleans up with only the cloud profile, after the runner profile is gone', async () => {
        const { controller } = prepare()
        const runId = await leaseAt(T, controller)
        rmSync(path.join(dir, 'runner.yaml'))

        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(0)

        expect(released(runId)).toBe(1)
    })

    it('cleanup --expired releases only expired leases, once', async () => {
        const { controller } = prepare()
        const expired = await leaseAt(T, controller)
        const live = await leaseAt(new Date(T.getTime() + 5 * HOUR_MS), controller)
        now = new Date(T.getTime() + 6.5 * HOUR_MS)

        await expect(main(['cleanup', profilePath(), '--expired'], controller)).resolves.toBe(0)

        expect(released(expired)).toBe(1)
        expect(schedulesFor(expired)).toEqual([])
        expect(cloud.deleteStackRequests).toEqual([{ stackName: `scn-${expired}`, at: '2026-03-02T16:00:00.000Z' }])
        expect(released(live)).toBe(0)
        expect(schedulesFor(live)).toHaveLength(2)

        const objects = new Map(cloud.objects)
        now = new Date(now.getTime() + 60_000)
        await expect(main(['cleanup', profilePath(), '--expired'], controller)).resolves.toBe(0)
        expect(released(expired)).toBe(1)
        expect(cloud.objects).toEqual(objects)
        expect(schedulesFor(live)).toHaveLength(2)
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

    it.each<[string, string, string[], string]>([
        ['run', 'manifest', [], 'manifest.json'],
        ['cleanup', 'manifest', ['--expired'], 'manifest.json'],
        ['run', 'receipt', [], 'receipts/earlier.json'],
        ['cleanup', 'receipt', ['--expired'], 'receipts/earlier.json'],
    ])(
        "%s still releases the other expired leases when one run's %s cannot be read",
        async (command, _, rest, name) => {
            const { controller } = prepare({ cloud: { expiration: new Date(T.getTime() + 24 * HOUR_MS) } })
            const broken = await leaseAt(T, controller)
            const expired = await leaseAt(T, controller)
            cloud.objects.set(`runs/${broken}/${name}`, 'not JSON')
            now = new Date(T.getTime() + 6.5 * HOUR_MS)

            await expect(main([command, profilePath(), ...rest], controller)).resolves.toBe(2)

            expect(released(expired)).toBe(1)
            expect(schedulesFor(expired)).toEqual([])
            expect(err.join('\n')).toContain(broken)
        }
    )

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

    it('sweeps expired leases before it admits a run', async () => {
        const { controller } = prepare({ cloud: { expiration: new Date(T.getTime() + 24 * HOUR_MS) } })
        const expired = await leaseAt(T, controller)
        now = new Date(T.getTime() + 7 * HOUR_MS)

        await main(['run', profilePath()], controller)

        expect(released(expired)).toBe(1)
        expect(schedulesFor(expired)).toEqual([])
    })

    it.each<[string, (fake: FakeCloud) => void]>([
        ['', () => undefined],
        [
            ', retrying a resource read that fails during teardown',
            (fake) => fake.failOnCall('describe-db-instances', 2),
        ],
        [
            ', judging an untyped tagged resource gone once its tag listing drops it',
            (fake) => fake.untyped.push('arn:aws:rds:us-east-1:000000000000:cluster-auto-backup:cab-0'),
        ],
        [', retrying a delete-stack that fails once', (fake) => fake.failOnCall('delete-stack')],
        [', listing the tagged resources again after a failed listing', (fake) => fake.failOnCall('get-resources', 3)],
        [
            ', keeping its host when the image parameter moves',
            (fake) => fake.beforeCall('update-stack', () => fake.parameterStore.set('/test/ubuntu/ami-id', 'ami-0b')),
        ],
    ])('creates the run stack, adds the reader, and leaves nothing billing%s', async (_, arrange) => {
        const { controller } = prepare()
        arrange(cloud)

        await expect(main(['run', profilePath()], controller)).resolves.toBe(0)

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
        ['describe-stacks', 'fails', 2],
        ['update-stack', 'fails', 1],
        ['describe-stacks', 'fails', 4],
    ])('tears everything down when %s %s (call %d)', async (operation, how, nth) => {
        const { controller } = prepare()
        if (how === 'fails') {
            cloud.failOnCall(operation, nth)
        } else {
            cloud.loseResponseOf(operation, nth)
        }

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
        expect(released(leasedRunId())).toBe(1)
    })

    it.each<[string, Setup, string]>([
        ['the host writes its failed marker', { cloud: { host: 'failed' } }, 'host/bootstrap.log'],
        ['the host misses its bootstrap deadline', { cloud: { host: 'silent' } }, 'not ready within 30m'],
        [
            'the host stays silent until the lease expires',
            {
                cloud: { host: 'silent' },
                profile: (p) => ({ ...p, host: { ...p.host, bootstrapDeadline: '720m' } }),
            },
            'only its teardown allowance',
        ],
        ['the stack rolls back its creation', { cloud: { rollsBack: 'create' } }, 'not CREATE_COMPLETE'],
        ['the stack rolls back the reader', { cloud: { rollsBack: 'update' } }, 'not UPDATE_COMPLETE'],
    ])('makes the run invalid and tears down when %s', async (_, setup, reason) => {
        const { controller } = prepare(setup)

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(reason)
        expect(cloud.deleteStackRequests).toEqual([])
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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(deletedAt! - interruptedAt!).toBeLessThan(60_000)
        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
    })

    it.each([
        ['as it resolves the host image', 'get-parameter'],
        ['as the host reports ready', 'list-objects-v2'],
    ])('creates nothing more when interrupted %s', async (_, operation) => {
        const { controller } = prepare()
        let createdBefore: number | undefined
        let interruptedAt: number | undefined
        cloud.beforeCall(operation, () => {
            if (interrupt && createdBefore === undefined) {
                createdBefore = cloud.resources.length
                interruptedAt = now.getTime()
                interrupt()
            }
        })

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(cloud.resources).toHaveLength(createdBefore!)
        expect(cloud.billable()).toEqual([])
        expect(now.getTime() - interruptedAt!).toBeLessThan(HOUR_MS / 6)
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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(cloud.billable()).toEqual([])
        expect(cloud.schedules.size).toBe(0)
    })

    it.each([
        ['the stack', 'get-schedule', 'too soon to create the stack'],
        ['the stack after it reads the host image', 'get-parameter', 'too soon to create the stack'],
        ['the reader', 'update-stack', 'too soon to add the reader'],
    ])('creates nothing more once the lease is too close to expiry to create %s', async (_, operation, reason) => {
        const { controller } = prepare()
        let jumped = false
        const jump = (): void => {
            if (!jumped && cloud.schedules.size === 2) {
                jumped = true
                now = new Date(now.getTime() + 5.5 * HOUR_MS)
            }
        }
        if (operation === 'update-stack') {
            cloud.beforeCall('list-objects-v2', () => cloud.stacks.size > 0 && jump())
        } else {
            cloud.beforeCall(operation, jump)
        }

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(reason)
        expect(cloud.resources.map(({ id }) => id).filter((id) => id.endsWith('-reader'))).toEqual([])
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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

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
        ['it cannot list what the run created', (fake) => fake.failOnCall('get-resources', 2), 'could not list'],
        ['releasing the lease fails', (fake) => fake.failOnCall('delete-schedule', 2), 'releasing its lease failed'],
        [
            'it cannot read its earlier receipts',
            (fake) => fake.failWhen('list-objects-v2', listsReceipts),
            'could not list the earlier receipts',
        ],
    ])('deletes the stack but keeps a schedule and names the cleanup when %s', async (_, arrange, reason) => {
        const { controller } = prepare()
        arrange(cloud)

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

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
            (fake) => fake.failOnCall('describe-db-cluster-snapshots', 2),
            () => undefined,
        ],
        [
            'AWS::SecretsManager::Secret',
            ', even after a cleanup that cannot read an earlier receipt',
            () => undefined,
            (fake) => fake.failOnCall('get-object', 2),
        ],
        [
            'AWS::SecretsManager::Secret',
            ', even when the run cannot list its earlier receipts',
            (fake) => fake.failWhen('list-objects-v2', listsReceipts),
            (fake) => fake.heal(),
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
        [
            'AWS::SecretsManager::Secret',
            ', even when the run stops before its cluster is visible',
            (fake) => {
                fake.hideCreationWhile(
                    () => ![...fake.stacks.values()].some(({ status }) => status.startsWith('DELETE'))
                )
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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        const left = cloud.billable().filter((resource) => resource.startsWith(type))
        expect(left).toHaveLength(1)
        expect(err.join('\n')).toContain(`- ${left[0]}`)
        expect(cloud.schedules.size).toBe(2)

        beforeCleanup(cloud)
        await expect(main(['cleanup', profilePath(), leasedRunId()], controller)).resolves.toBe(2)
        await expect(main(['cleanup', profilePath(), leasedRunId()], controller)).resolves.toBe(2)

        expect(cloud.schedules.size).toBe(2)
    })

    it.each<[string, Partial<FakeCloudOptions>, string[], string]>([
        [
            'could not look it up',
            {},
            ['describe-db-clusters', 'list-secrets'],
            'could not list the secret and backups of cluster',
        ],
        [
            'could list nothing',
            {},
            ['describe-stack-resources', 'get-resources', 'describe-db-clusters', 'list-secrets'],
            'could not list the secret and backups of cluster',
        ],
        ['found its stack already deleted', { rollsBack: 'create' }, [], 'until the tag listings catch up'],
    ])(
        'names a secret that outlives the stack in a later cleanup, when the run %s',
        async (_, options, failing, says) => {
            const { controller } = prepare({
                cloud: { ...options, outlives: ['AWS::SecretsManager::Secret'] },
                profile: (p) => ({ ...p, admission: { ...p.admission, teardownAllowance: '2m' } }),
            })
            failing.forEach((operation) => cloud.failWhen(operation, () => cloud.schedules.size > 0))
            onSleep = () => {
                if (failing.length > 0 && cloud.resources.length > 0) {
                    interrupt?.()
                }
            }

            await expect(main(['run', profilePath()], controller)).resolves.toBe(2)
            expect(err.join('\n')).toContain(says)

            cloud.heal()
            err.length = 0
            await expect(main(['cleanup', profilePath(), leasedRunId()], controller)).resolves.toBe(2)
            expect(err.join('\n')).toContain('until the tag listings catch up')
            expect(cloud.schedules.size).toBe(2)

            err.length = 0
            now = new Date(now.getTime() + HOUR_MS / 3)
            await expect(main(['cleanup', profilePath(), leasedRunId()], controller)).resolves.toBe(2)

            const [secret] = cloud.billable().filter((resource) => resource.startsWith('AWS::SecretsManager::Secret'))
            expect(err.join('\n')).toContain(`- ${secret}`)
            expect(cloud.schedules.size).toBe(2)
        }
    )

    it.each([
        ['its receipt', false],
        ['no receipt', true],
    ])('refuses a new run while an expired run with %s still holds resources', async (_, forgetReceipt) => {
        const { controller } = prepare({ cloud: { outlives: ['AWS::EC2::Volume'] } })
        await main(['run', profilePath()], controller)
        const runId = leasedRunId()
        if (forgetReceipt) {
            ;[...cloud.objects.keys()]
                .filter((key) => key.startsWith(`runs/${runId}/receipts/`))
                .forEach((key) => cloud.objects.delete(key))
        }
        const at = new Date(T.getTime() + 7 * HOUR_MS)
        now = at

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(out.filter((line) => line.startsWith('Leased run'))).toHaveLength(1)
        expect(err.join('\n')).toContain('an expired run still holds resources')
        expect(now.getTime() > at.getTime()).toBe(forgetReceipt)
    })

    it('changes nothing on a second cleanup of a torn-down run', async () => {
        const { controller } = prepare()
        await main(['run', profilePath()], controller)
        const runId = leasedRunId()
        const resources = structuredClone(cloud.resources)

        await expect(main(['cleanup', profilePath(), runId], controller)).resolves.toBe(0)

        expect(cloud.resources).toEqual(resources)
        expect(cloud.stacks.size).toBe(0)
        expect(cloud.schedules.size).toBe(0)
    })

    it('deletes the stack by schedule when the controller dies after creating it', async () => {
        const { controller } = prepare({ cloud: { host: 'silent' } })
        let waitingForHost!: () => void
        const died = new Promise<void>((resolve) => (waitingForHost = resolve))
        onSleep = () => {
            waitingForHost()
            return new Promise(() => undefined)
        }
        void main(['run', profilePath()], controller)
        await died
        const runId = leasedRunId()
        expect(cloud.billable()).not.toEqual([])

        now = new Date(T.getTime() + 6 * HOUR_MS + 60_000)
        cloud.tick()

        expect(cloud.deleteStackRequests).toEqual([{ stackName: `scn-${runId}`, at: '2026-03-02T16:00:00.000Z' }])
        expect(cloud.billable()).toEqual([])
    })
})
