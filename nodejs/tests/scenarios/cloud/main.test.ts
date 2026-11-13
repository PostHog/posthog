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
const OWNER = 'arn:aws:sts::000000000000:assumed-role/developers/person'

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
    ssoToken?: { expiresAt: Date; refreshToken?: string }
    env?: NodeJS.ProcessEnv
}

const sha256 = (text: string): string => createHash('sha256').update(text).digest('hex')

describe('cloud controller', () => {
    let dir: string
    let now: Date
    let cloud: FakeCloud
    let out: string[]
    let err: string[]

    const profilePath = (): string => path.join(dir, 'profile.yaml')

    function prepare({ profile = (p) => p, cloud: options = {}, published = true, ssoToken, env = {} }: Setup = {}): {
        controller: Controller
    } {
        writeFileSync(profilePath(), stringify(profile(structuredClone(PROFILE))))
        writeFileSync(path.join(dir, 'runner.yaml'), stringify({ name: 'test-current', traffic: {}, settings: {} }))
        cloud = new FakeCloud({ now: () => now, expiration: new Date(T.getTime() + 12 * HOUR_MS), ...options })
        if (ssoToken) {
            const cache = path.join(dir, '.aws', 'sso', 'cache')
            mkdirSync(cache, { recursive: true })
            const name = createHash('sha1').update(cloud.ssoSession!).digest('hex')
            writeFileSync(
                path.join(cache, `${name}.json`),
                JSON.stringify({ ...ssoToken, expiresAt: ssoToken.expiresAt.toISOString() })
            )
        }
        const controller: Controller = {
            aws: cloud,
            origin: { head: () => COMMIT, published: (commit) => Promise.resolve(published && commit === COMMIT) },
            now: () => now,
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
            ssoToken: { expiresAt: new Date(T.getTime() + HOUR_MS), refreshToken: 'example-refresh' },
        })

        await expect(main(['run', profilePath()], controller)).resolves.toBe(0)

        expect(err.join('\n')).toContain('stack-delete schedules')
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
        ['an SSO session with no cached token', { cloud: { ssoSession: 'test-sso' } }, 'aws sso login'],
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
        ['a commit that is not on origin', { published: false }, COMMIT],
        ['a writer class that is not orderable', { cloud: { orderable: ['db.serverless'] } }, 'db.r8g.2xlarge'],
        [
            'a missing permission',
            { cloud: { denied: ['logs:FilterLogEvents'] } },
            'Missing permission logs:FilterLogEvents',
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
    ])('refuses %s before it writes anything', async (_, setup, reason) => {
        const { controller } = prepare(setup)

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(reason)
        expect(cloud.objects.size).toBe(0)
        expect(cloud.schedules.size).toBe(0)
    })

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

    it('sweeps expired leases before it admits a run', async () => {
        const { controller } = prepare({ cloud: { expiration: new Date(T.getTime() + 24 * HOUR_MS) } })
        const expired = await leaseAt(T, controller)
        now = new Date(T.getTime() + 7 * HOUR_MS)

        await main(['run', profilePath()], controller)

        expect(released(expired)).toBe(1)
        expect(schedulesFor(expired)).toEqual([])
    })
})
