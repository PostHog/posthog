import { createHash } from 'crypto'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { stringify } from 'yaml'

import { parseJSON } from '~/common/utils/json-parse'

import { FakeCloud, FakeCloudOptions } from './fake-cloud'
import { PROFILE } from './fixtures'
import { lease } from './lease'
import { Controller, main } from './main'
import { loadRunInputs } from './profile'

const T = new Date('2026-03-02T10:00:00.000Z')
const HOUR_MS = 60 * 60 * 1000
const COMMIT = 'c0ffee0000000000000000000000000000000000'
const OWNER = 'arn:aws:sts::000000000000:assumed-role/scenario-run-controller/person'
const OTHER_ACCOUNT = '111111111111'

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
    let interrupt: (() => void) | undefined
    let onSleep: (() => Promise<void> | void) | undefined

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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

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
        const { controller } = prepare(setup)

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(err.join('\n')).toContain(reason)
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
        const { controller } = prepare({ cloud: options })
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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(exitCode)

        const runId = leasedRunId()
        expect(deletedAt! - doneAt!).toBeLessThan(HOUR_MS / 6)
        expect(cloud.resources.find(({ logicalId }) => logicalId === 'Reader')).toMatchObject({ seeded: true })
        expect(parseJSON(cloud.objects.get(`runs/${runId}/host/done`)!)).toMatchObject({ exitCode })
        expect(cloud.objects.has(`runs/${runId}/evidence/SHA256SUMS`)).toBe(true)
        expect(cloud.billable()).toEqual([])
    })

    it.each<[string, Partial<FakeCloudOptions>, (fake: FakeCloud) => void, boolean]>([
        ['it is interrupted while the card runs', {}, () => undefined, true],
        ['the card ignores the stop', { card: { ignoresStop: true } }, () => undefined, false],
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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

        expect(evidenceAtDelete).toBe(uploaded)
        expect(err.join('\n').includes('did not finish cleanly')).toBe(!uploaded)
        expect(deletedAt! - interruptedAt!).toBeLessThan(HOUR_MS / 6)
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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

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

        await expect(main(['run', profilePath()], controller)).resolves.toBe(2)

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
        ['it cannot list what the run created', (fake) => fake.failOnCall('get-resources', 1), 'could not list'],
        ['releasing the lease fails', (fake) => fake.failOnCall('delete-schedule', 2), 'releasing its lease failed'],
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
        void main(['run', profilePath()], controller)
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
