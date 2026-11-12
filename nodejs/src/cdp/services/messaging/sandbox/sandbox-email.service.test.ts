import { defaultConfig } from '~/common/config/config'
import { StallingValkeyProxy } from '~/common/redis/_tests/stalling-valkey-proxy'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { PostgresUse } from '~/common/utils/db/postgres'
import { waitForExpect } from '~/tests/helpers/expectations'

import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'
import { SES_REJECTED, SES_SERVER_ERROR, SES_THROTTLE, SesReply } from './_tests/fake-ses-endpoint'
import { SANDBOX_FROM_ADDRESS, SandboxFaults, useSandboxWorld } from './_tests/sandbox-world'
import { SandboxSendOutcome, SandboxSendRequest } from './sandbox-email.service'

describe('SandboxEmailService', () => {
    const world = useSandboxWorld()
    const personal = (text: string): string => text.replace(/([^\s@<>",]+)@/g, `$1-${world.team.id}@`)
    const member = () => personal('Member@Example.com')

    beforeEach(async () => {
        await world.addMember(member())
    })

    const request = (overrides: Partial<SandboxSendRequest> = {}): SandboxSendRequest => {
        const sent: SandboxSendRequest = {
            teamId: world.team.id,
            hogFlowId: 'flow-1',
            invocationId: 'run-1',
            actionId: 'action_email_sandbox_1',
            flowVersion: 4,
            isTest: false,
            workflowEmailPaused: false,
            email: { to: { email: 'member@example.com', name: 'Mem' }, subject: 'Hi', text: 'Hello' },
            claimSesSlot: () => Promise.resolve(true),
            ...overrides,
            capClaimId: overrides.capClaimId ?? `${overrides.invocationId ?? 'run-1'}:action_email_sandbox_1`,
        }
        const email = sent.email as { to?: { email?: string } }
        return {
            ...sent,
            email: email.to?.email ? { ...email, to: { ...email.to, email: personal(email.to.email) } } : email,
            optOuts: sent.optOuts?.map((optOut) => ({ ...optOut, identifier: personal(optOut.identifier) })),
        }
    }

    const to = (email: string) => ({ email: { to: { email }, subject: 'Hi', text: 'Hello' } })
    const recipients = () => world.ses.delivered.map((email) => email.to.map(({ address }) => address)).flat()

    const optOut = async (identifier: string, categoryId: string) => {
        await world.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
             VALUES (gen_random_uuid(), $1, $2, $3, NOW(), NOW(), false)`,
            [world.team.id, personal(identifier), JSON.stringify({ [categoryId]: 'OPTED_OUT' })],
            'test:opt-out'
        )
    }

    it('delivers one email to the stored member spelling, from the organization, with the run tags', async () => {
        await expect(world.service().send(request())).resolves.toEqual({ status: 'accepted', messageId: 'ses-1' })

        expect(world.ses.delivered).toEqual([
            expect.objectContaining({
                from: { name: `${world.organizationName} via PostHog`, address: SANDBOX_FROM_ADDRESS },
                to: [{ name: 'Mem', address: member() }],
                subject: 'Hi',
                tags: {
                    ph_sbx_team: String(world.team.id),
                    ph_sbx_flow: 'flow-1',
                    ph_sbx_run: 'run-1',
                    ph_sbx_action: 'action_email_sandbox_1',
                    ph_sbx_version: '4',
                    ph_sbx_test: 'false',
                },
            }),
        ])
    })

    type Setup = { enabled?: boolean; faults?: SandboxFaults; request?: Partial<SandboxSendRequest> }

    it.each<[string, () => Promise<Setup>, SandboxSendOutcome]>([
        [
            'the kill switch is off',
            () => Promise.resolve({ enabled: false }),
            { status: 'skipped', reason: 'sending_disabled' },
        ],
        [
            'the payload has no subject',
            () => Promise.resolve({ request: { email: { to: { email: 'member@example.com' }, text: 'x' } } }),
            { status: 'failed', reason: 'render_failed' },
        ],
        [
            'the action id has a character SES tags cannot carry',
            () => Promise.resolve({ request: { actionId: 'email.step' } }),
            { status: 'failed', reason: 'unsupported_action_id' },
        ],
        [
            'the team has no sandbox sender',
            async () => {
                await world.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'DELETE FROM posthog_integration WHERE team_id = $1',
                    [world.team.id],
                    'test:unprovision'
                )
                return {}
            },
            { status: 'skipped', reason: 'sandbox_not_provisioned' },
        ],
        [
            'the provisioning read fails',
            async () => ({ faults: { provisioningDb: await world.deadPostgres() } }),
            { status: 'retry', reason: 'authorization_unavailable' },
        ],
        ...[
            'a@example.com, b@example.com',
            '"Boss" <a@example.com>',
            'member@example.com\r\nBcc: b@example.com',
            'not-an-address',
        ].map((address): [string, () => Promise<Setup>, SandboxSendOutcome] => [
            `the recipient is ${JSON.stringify(address)}`,
            () => Promise.resolve({ request: to(address) }),
            { status: 'skipped', reason: 'invalid_recipient' },
        ]),
        [
            'the recipient is suppressed',
            async () => {
                await world.suppression.recordHardBounces(world.team.id, [member()], 'smtp; 550 5.1.1 user unknown')
                return {}
            },
            { status: 'skipped', reason: 'suppressed' },
        ],
        [
            'the suppression read fails',
            async () => ({ faults: { recipientsDb: await world.deadPostgres() } }),
            { status: 'retry', reason: 'authorization_unavailable' },
        ],
        [
            'the recipient is not a member',
            () => Promise.resolve({ request: to('stranger@example.com') }),
            { status: 'skipped', reason: 'not_member' },
        ],
        [
            'the organization is blocked',
            async () => {
                await world.blockOrganization()
                return {}
            },
            { status: 'skipped', reason: 'organization_blocked' },
        ],
        [
            'the member read fails',
            async () => ({ faults: { authorizationDb: await world.deadPostgres() } }),
            { status: 'retry', reason: 'authorization_unavailable' },
        ],
        [
            'the tenant mirror is stale',
            async () => {
                await world.setTenant('ENABLED', new Date(Date.now() - 600_000))
                return {}
            },
            { status: 'retry', reason: 'pause_state_unavailable' },
        ],
        [
            'the tenant is paused',
            async () => {
                await world.setTenant('DISABLED', new Date())
                return {}
            },
            { status: 'skipped', reason: 'tenant_paused' },
        ],
        [
            'the cap storage fails',
            () => Promise.resolve({ faults: { capsLimiter: world.unreachableLimiter() } }),
            { status: 'retry', reason: 'cap_storage_unavailable' },
        ],
    ])('sends nothing when %s', async (_name, setup, outcome) => {
        const { enabled, faults, request: overrides } = await setup()

        await expect(world.service({ enabled, faults }).send(request(overrides))).resolves.toEqual(outcome)
        expect(world.ses.delivered).toEqual([])
    })

    it('spends one daily allowance per member on each delivered email, and refuses once it is gone', async () => {
        const service = world.service({ caps: { team: 5, recipient: 1 } })

        await expect(service.send(request())).resolves.toMatchObject({ status: 'accepted' })
        await expect(service.send(request({ invocationId: 'run-2' }))).resolves.toEqual({
            status: 'skipped',
            reason: 'daily_cap_reached',
        })
        expect(recipients()).toEqual([member()])
    })

    const capped = (): Promise<FrequencyCapCheck> =>
        Promise.resolve({ capped: true, nextSlotAt: Date.now() + 3_600_000, holdHours: null })

    const oneMarketingSlot = () => {
        let slots = 1
        return (): Promise<FrequencyCapCheck> => {
            if (slots === 0) {
                return capped()
            }
            slots -= 1
            return Promise.resolve({ capped: false })
        }
    }

    it.each([
        ['the trimmed address', 'member@example.com', ' member@example.com '],
        ['the padded address its unsubscribe link carried', ' member@example.com ', ' member@example.com '],
        ['the stored member spelling', 'Member@Example.com', ' member@example.com '],
        ['the lowercase address a sandbox unsubscribe link carries', 'member@example.com', 'MEMBER@example.com'],
    ])(
        'refuses a recipient who opted out under %s, and keeps their allowances for other categories',
        async (_name, optedOutIdentifier, renderedAddress) => {
            await optOut(optedOutIdentifier, 'news')
            const service = world.service({ caps: { team: 1, recipient: 1 } })
            const frequencyCap = oneMarketingSlot()
            const marketing = (categoryId: string) =>
                request({ ...to(renderedAddress), categoryId, categoryType: 'marketing', frequencyCap })

            await expect(service.send(marketing('news'))).resolves.toEqual({ status: 'skipped', reason: 'opted_out' })
            expect(world.ses.delivered).toEqual([])

            await expect(service.send(marketing('product'))).resolves.toMatchObject({ status: 'accepted' })
            expect(recipients()).toEqual([member()])
        }
    )

    it.each<[string, SesReply, SandboxSendOutcome, SandboxSendOutcome]>([
        [
            'throttles it',
            SES_THROTTLE,
            { status: 'retry', reason: 'ses_throttled' },
            { status: 'accepted', messageId: 'ses-1' },
        ],
        [
            'rejects it',
            SES_REJECTED,
            { status: 'failed', reason: 'ses_rejected' },
            { status: 'accepted', messageId: 'ses-1' },
        ],
        [
            'fails in a way that may have sent it',
            SES_SERVER_ERROR,
            { status: 'retry', reason: 'ses_transient' },
            { status: 'skipped', reason: 'daily_cap_reached' },
        ],
    ])(
        'charges a step visit replayed after SES %s only when SES may have taken the email',
        async (_case, reply, first, replayed) => {
            await world.addMember(personal('other@example.com'))
            const service = world.service({ caps: { team: 1, recipient: 1 } })
            world.ses.replyNext(reply)

            await expect(service.send(request())).resolves.toEqual(first)
            await expect(service.send(request())).resolves.toEqual(replayed)
            await expect(service.send(request(to('other@example.com')))).resolves.toEqual({
                status: 'skipped',
                reason: 'daily_cap_reached',
            })
        }
    )

    it('charges a step visit replayed after its worker died while SES took the email', async () => {
        const service = world.service({ caps: { team: 5, recipient: 1 } })
        world.ses.replyNext({ kind: 'deliver-without-reply' })

        const diedWaitingForSes = service.send(request())
        await waitForExpect(() => expect(world.ses.delivered).toHaveLength(1))

        await expect(service.send(request())).resolves.toEqual({ status: 'skipped', reason: 'daily_cap_reached' })
        expect(recipients()).toEqual([member()])
        world.ses.dropConnections()
        await expect(diedWaitingForSes).resolves.toEqual({ status: 'retry', reason: 'ses_transient' })
    })

    it('sends one email when two overlapping attempts of one step visit both hold its claim at caps of one', async () => {
        let claims = 0
        let bothClaimed: () => void = () => undefined
        const otherClaimArrived = new Promise<void>((resolve) => (bothClaimed = resolve))
        const claimsOverlap: RedisV2 = {
            ...world.valkey,
            useClient: async (options, callback) => {
                const result = await world.valkey.useClient(options, callback)
                if (claims < 2) {
                    claims += 1
                    if (claims === 2) {
                        bothClaimed()
                    }
                    await otherClaimArrived
                }
                return result
            },
        }
        const capsLimiter = new RateLimiterService(claimsOverlap, { name: 'claims-overlap' })
        const service = world.service({ caps: { team: 1, recipient: 1 }, faults: { capsLimiter } })

        const outcomes = await Promise.all([service.send(request()), service.send(request())])

        expect(outcomes).toEqual(
            expect.arrayContaining([
                { status: 'accepted', messageId: 'ses-1' },
                { status: 'retry', reason: 'cap_storage_unavailable' },
            ])
        )
        expect(recipients()).toEqual([member()])
        await expect(service.send(request())).resolves.toEqual({ status: 'skipped', reason: 'daily_cap_reached' })
    })

    it('sends nothing and retries when the cap store stops answering before the claim is charged', async () => {
        const store = new StallingValkeyProxy({
            host: defaultConfig.CDP_REDIS_HOST,
            port: defaultConfig.CDP_REDIS_PORT,
        })
        const pool = createRedisV2PoolFromConfig({
            connection: {
                url: '127.0.0.1',
                options: {
                    port: await store.start(),
                    password: defaultConfig.CDP_REDIS_PASSWORD,
                    retryStrategy: () => null,
                },
                name: 'sandbox-service-stalls-after-claim',
                exitOnRepeatedErrors: false,
            },
            poolMinSize: 0,
            poolMaxSize: 1,
        })
        const stallsAfterClaim: RedisV2 = {
            ...pool,
            useClient: async (options, callback) => {
                const result = await pool.useClient(options, callback)
                store.stopAnswering()
                return result
            },
        }
        const capsLimiter = new RateLimiterService(stallsAfterClaim, { name: 'stalls-after-claim' })

        try {
            await expect(world.service({ faults: { capsLimiter } }).send(request())).resolves.toEqual({
                status: 'retry',
                reason: 'cap_storage_unavailable',
            })
        } finally {
            store.stop()
        }
        expect(world.ses.attempts).toBe(0)
    })

    it('charges a step visit again when it is replayed after SES accepted it', async () => {
        const service = world.service({ caps: { team: 5, recipient: 2 } })

        await expect(service.send(request())).resolves.toMatchObject({ status: 'accepted' })
        await expect(service.send(request())).resolves.toMatchObject({ status: 'accepted' })
        await expect(service.send(request())).resolves.toEqual({ status: 'skipped', reason: 'daily_cap_reached' })
        expect(recipients()).toEqual([member(), member()])
    })

    it.each([
        ['suppression', 'posthog_messagesuppression'],
        ['preference', 'posthog_messagerecipientpreference'],
    ])('retries a send whose %s read waits behind a lock past its deadline', async (_read, table) => {
        const release = await world.lockTable(table)
        try {
            await expect(world.service({ faults: { recipientReadTimeoutMs: 200 } }).send(request())).resolves.toEqual({
                status: 'retry',
                reason: 'authorization_unavailable',
            })
        } finally {
            await release()
        }
        expect(world.ses.delivered).toEqual([])
    })

    const accepted: SandboxSendOutcome = { status: 'accepted', messageId: 'ses-1' }
    const optedOut: SandboxSendOutcome = { status: 'skipped', reason: 'opted_out' }

    it.each<[string, Partial<SandboxSendRequest>, SandboxSendOutcome]>([
        [
            'a run opt-out from its category',
            { optOuts: [{ identifier: 'member@example.com', categoryId: 'news' }] },
            optedOut,
        ],
        [
            'a run opt-out from all marketing',
            { optOuts: [{ identifier: 'member@example.com', categoryId: '$all' }] },
            optedOut,
        ],
        [
            'a run opt-out from its category under another spelling',
            { optOuts: [{ identifier: 'MEMBER@example.com', categoryId: 'news' }] },
            optedOut,
        ],
        [
            'a run opt-out from another category',
            { optOuts: [{ identifier: 'member@example.com', categoryId: 'other' }] },
            accepted,
        ],
        ['a reached frequency cap', { frequencyCap: capped }, { status: 'skipped', reason: 'frequency_capped' }],
        ['a reached frequency cap on a test send', { frequencyCap: capped, isTest: true }, accepted],
    ])('applies %s to a marketing send', async (_case, overrides, outcome) => {
        await expect(
            world.service().send(request({ categoryId: 'news', categoryType: 'marketing', ...overrides }))
        ).resolves.toEqual(outcome)
        expect(recipients()).toEqual(outcome.status === 'accepted' ? [member()] : [])
    })
})
