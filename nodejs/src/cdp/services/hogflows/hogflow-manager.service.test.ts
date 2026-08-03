import '~/tests/helpers/mocks/date.mock'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HogFlow } from '~/cdp/schema/hogflow'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { waitForExpect } from '~/tests/helpers/expectations'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { insertHogFlow } from '../../_tests/fixtures-hogflows'
import { HogFlowManagerService } from './hogflow-manager.service'

describe('HogFlowManager', () => {
    jest.setTimeout(2000)
    let hub: Hub
    let manager: HogFlowManagerService

    let hogFlows: HogFlow[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFlowManagerService(hub.postgres, hub.pubSub, hub.encryptedFields)

        const team = await getTeam(hub.postgres, 2)

        teamId1 = await createTeam(hub.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.postgres, team!.organization_id)

        hogFlows = []

        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 1')
                    .withTeamId(teamId1)
                    .withStatus('active')
                    .build()
            )
        )

        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 1 - other')
                    .withTeamId(teamId1)
                    .withStatus('active')
                    .build()
            )
        )

        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 2')
                    .withTeamId(teamId2)
                    .withStatus('active')
                    .build()
            )
        )
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns the hog flow', async () => {
        let items = await manager.getHogFlowsForTeam(teamId1)
        expect(items.map((item) => item.team_id)).toEqual([teamId1, teamId1])

        expect(
            forSnapshot(items, {
                overrides: {
                    team_id: 'TEAM_ID',
                    created_at: 'CREATED_AT',
                    updated_at: 'UPDATED_AT',
                },
            })
        ).toMatchSnapshot()

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogflow SET name='Test Hog Flow team 1 updated', updated_at = NOW() WHERE id = $1`,
            [hogFlows[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        manager['onHogFlowsReloaded'](teamId1, [hogFlows[0].id])

        items = await manager.getHogFlowsForTeam(teamId1)

        expect(items.find((item) => item.id === hogFlows[0].id)).toMatchObject({
            id: hogFlows[0].id,
            name: 'Test Hog Flow team 1 updated',
        })
    })

    describe('cache staleness bounds', () => {
        // Own timeout: the polling window below plus DB round-trips can exceed the suite's 2s default
        it('picks up an edit without a reload notification once the background refresh age passes', async () => {
            const baseNow = Date.now()
            try {
                let items = await manager.getHogFlowsForTeam(teamId1)
                expect(items.find((item) => item.id === hogFlows[0].id)?.name).toBe('Test Hog Flow team 1')

                // Edit WITHOUT dispatching the reload notification - the missed-publish case
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `UPDATE posthog_hogflow SET name='Renamed without notification', updated_at = NOW() WHERE id = $1`,
                    [hogFlows[0].id],
                    'testKey'
                )

                // Still within the background refresh age: served from cache
                items = await manager.getHogFlowsForTeam(teamId1)
                expect(items.find((item) => item.id === hogFlows[0].id)?.name).toBe('Test Hog Flow team 1')

                // Past the background age (30s + up to 24s jitter) but under the 2 min hard cap:
                // this get serves stale and kicks off a non-blocking refresh
                jest.spyOn(Date, 'now').mockReturnValue(baseNow + 60_000)
                items = await manager.getHogFlowsForTeam(teamId1)
                expect(items.find((item) => item.id === hogFlows[0].id)?.name).toBe('Test Hog Flow team 1')

                // The background refresh lands and the edit becomes visible - self-healed with no
                // markForRefresh. Guards against reverting to the LazyLoader defaults (5 min
                // blocking-only refresh), which would leave this stale until well past 60s.
                await waitForExpect(async () => {
                    const refreshed = await manager.getHogFlowsForTeam(teamId1)
                    expect(refreshed.find((item) => item.id === hogFlows[0].id)?.name).toBe(
                        'Renamed without notification'
                    )
                }, 1500)
            } finally {
                jest.spyOn(Date, 'now').mockReturnValue(baseNow)
            }
        }, 10000)
    })

    describe('getHogFlowIdsForTeam', () => {
        it('returns function IDs', async () => {
            const result = await manager.getHogFlowIdsForTeams([teamId1, teamId2])

            expect(result[teamId1]).toHaveLength(2)
            expect(result[teamId1]).toContain(hogFlows[0].id)
            expect(result[teamId1]).toContain(hogFlows[1].id)

            expect(result[teamId2]).toHaveLength(1)
            expect(result[teamId2]).toContain(hogFlows[2].id)
        })

        it('returns empty arrays for teams with no matching functions', async () => {
            const nonExistentTeamId = teamId2 + 1
            const result = await manager.getHogFlowIdsForTeams([nonExistentTeamId])
            expect(result[nonExistentTeamId]).toEqual([])
        })

        it('handles archived hog flows', async () => {
            const originalResult = await manager.getHogFlowIdsForTeams([teamId1, teamId2])
            expect(originalResult[teamId1]).toHaveLength(2)

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET status='archived', updated_at = NOW() WHERE id = $1`,
                [hogFlows[0].id],
                'testKey'
            )

            manager['onHogFlowsReloaded'](teamId1, [hogFlows[0].id])

            const result = await manager.getHogFlowIdsForTeams([teamId1])
            expect(result[teamId1]).toHaveLength(1)
            expect(result[teamId1]).not.toContain(hogFlows[0].id)
        })
    })

    describe('encrypted inputs', () => {
        it('decrypts and merges secret inputs into the matching action before execution', async () => {
            const flow = await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Flow with secret webhook')
                    .withTeamId(teamId1)
                    .withStatus('active')
                    .withWorkflow({
                        actions: {
                            trigger: { type: 'trigger', config: { type: 'event', filters: {} } },
                            send_webhook: {
                                type: 'function',
                                config: {
                                    template_id: 'template-webhook',
                                    inputs: { url: { value: 'https://example.com' } },
                                },
                            },
                            exit: { type: 'exit', config: {} },
                        },
                        edges: [
                            { from: 'trigger', to: 'send_webhook', type: 'continue' },
                            { from: 'send_webhook', to: 'exit', type: 'continue' },
                        ],
                    })
                    .build()
            )

            // The API stores secret inputs Fernet-encrypted, stripped out of the plaintext `actions`.
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET encrypted_inputs = $2 WHERE id = $1`,
                [
                    flow.id,
                    hub.encryptedFields.encrypt(
                        JSON.stringify({ send_webhook: { api_key: { value: 'super-secret-key' } } })
                    ),
                ],
                'testKey'
            )
            manager['onHogFlowsReloaded'](teamId1, [flow.id])

            const loaded = await manager.getHogFlow(flow.id)
            const action = loaded?.actions.find((a) => a.id === 'send_webhook')
            expect(action).not.toBeUndefined()

            // Secret folded back in alongside the untouched plaintext input, keyed by action id.
            expect((action!.config as { inputs: Record<string, unknown> }).inputs).toEqual({
                url: { value: 'https://example.com' },
                api_key: { value: 'super-secret-key' },
            })
            // The ciphertext blob never rides along on the in-memory flow.
            expect(loaded).not.toHaveProperty('encrypted_inputs')
        })

        it('re-merges a webhook trigger secret into hogFlow.trigger, not just the trigger action', async () => {
            const flow = await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Webhook-triggered flow')
                    .withTeamId(teamId1)
                    .withStatus('active')
                    .withWorkflow({
                        actions: {
                            trigger: {
                                type: 'trigger',
                                config: { type: 'webhook', template_id: 'template-source-webhook', inputs: {} },
                            },
                            exit: { type: 'exit', config: {} },
                        },
                        edges: [{ from: 'trigger', to: 'exit', type: 'continue' }],
                    })
                    .build()
            )

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET encrypted_inputs = $2 WHERE id = $1`,
                [
                    flow.id,
                    hub.encryptedFields.encrypt(
                        JSON.stringify({ trigger: { auth_header: { value: 'Bearer secret' } } })
                    ),
                ],
                'testKey'
            )
            manager['onHogFlowsReloaded'](teamId1, [flow.id])

            const loaded = await manager.getHogFlow(flow.id)
            // The source-webhook consumer builds its function from hogFlow.trigger, so the secret must
            // land there too or a webhook trigger would run without its configured auth header.
            expect((loaded!.trigger as { inputs: Record<string, unknown> }).inputs).toEqual({
                auth_header: { value: 'Bearer secret' },
            })
        })

        it('lets the encrypted value take precedence over plaintext left in actions', async () => {
            const flow = await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Flow with plaintext and encrypted secret')
                    .withTeamId(teamId1)
                    .withStatus('active')
                    .withWorkflow({
                        actions: {
                            trigger: { type: 'trigger', config: { type: 'event', filters: {} } },
                            // A row not yet re-saved since encryption shipped: the secret still sits in plaintext here...
                            send_webhook: {
                                type: 'function',
                                config: {
                                    template_id: 'template-webhook',
                                    inputs: { api_key: { value: 'stale-plaintext' } },
                                },
                            },
                            exit: { type: 'exit', config: {} },
                        },
                        edges: [
                            { from: 'trigger', to: 'send_webhook', type: 'continue' },
                            { from: 'send_webhook', to: 'exit', type: 'continue' },
                        ],
                    })
                    .build()
            )

            // ...and also in the encrypted column with the current value.
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET encrypted_inputs = $2 WHERE id = $1`,
                [
                    flow.id,
                    hub.encryptedFields.encrypt(JSON.stringify({ send_webhook: { api_key: { value: 'current' } } })),
                ],
                'testKey'
            )
            manager['onHogFlowsReloaded'](teamId1, [flow.id])

            const loaded = await manager.getHogFlow(flow.id)
            const action = loaded?.actions.find((a) => a.id === 'send_webhook')
            expect((action!.config as { inputs: Record<string, unknown> }).inputs).toEqual({
                api_key: { value: 'current' },
            })
        })

        it('keeps the flow (fail-open) when encrypted_inputs cannot be decrypted', async () => {
            const flow = await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Undecryptable flow')
                    .withTeamId(teamId1)
                    .withStatus('active')
                    .build()
            )

            // Not valid Fernet ciphertext (e.g. key skew / corruption): decrypt throws internally.
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET encrypted_inputs = $2 WHERE id = $1`,
                [flow.id, 'not-a-valid-fernet-token'],
                'testKey'
            )
            manager['onHogFlowsReloaded'](teamId1, [flow.id])

            // The whole flow load must not throw - the flow is returned, just without its secrets.
            const loaded = await manager.getHogFlow(flow.id)
            expect(loaded).not.toBeNull()
            expect(loaded).not.toHaveProperty('encrypted_inputs')
        })
    })
})
