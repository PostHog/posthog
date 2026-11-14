import { createHash } from 'crypto'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
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
    baseline: { schedulerRole: 'arn:aws:iam::000000000000:role/test-scheduler', evidenceBucket: 'test-evidence' },
    engineVersion: '16.4',
    writerClass: 'db.r8g.2xlarge',
    readerAcu: { min: 1, max: 32 },
    host: { class: 'm7i.8xlarge', ebsGb: 100 },
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
    arrange?: (cloud: FakeCloud) => void
}

const sha256 = (text: string): string => createHash('sha256').update(text).digest('hex')

describe('cloud controller', () => {
    let dir: string
    let now: Date
    let cloud: FakeCloud
    let out: string[]
    let err: string[]

    const profilePath = (): string => path.join(dir, 'profile.yaml')

    function prepare({
        profile = (p) => p,
        cloud: options = {},
        published = true,
        arrange = () => undefined,
    }: Setup = {}): {
        controller: Controller
    } {
        writeFileSync(profilePath(), stringify(profile(structuredClone(PROFILE))))
        writeFileSync(path.join(dir, 'runner.yaml'), stringify({ name: 'test-current', traffic: {}, settings: {} }))
        cloud = new FakeCloud({ now: () => now, ...options })
        arrange(cloud)
        const controller: Controller = {
            aws: cloud,
            origin: { head: () => COMMIT, published: (commit) => Promise.resolve(published && commit === COMMIT) },
            now: () => now,
            env: { HOME: dir },
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
        ['a commit that is not on origin', { published: false }, COMMIT],
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

    it('cleans up with only the cloud profile, after the runner profile is gone', async () => {
        const { controller } = prepare()
        const runId = await leaseAt(T, controller)
        rmSync(path.join(dir, 'runner.yaml'))

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
})
