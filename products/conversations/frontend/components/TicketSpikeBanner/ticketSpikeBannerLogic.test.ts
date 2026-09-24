import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import type { TicketPatternApi } from '../../generated/api.schemas'
import { ticketSpikeBannerLogic } from './ticketSpikeBannerLogic'

const SPIKE = {
    topic: 'Exports time out',
    summary: 'Several customers report exports failing part way through.',
    ticket_ids: ['ticket-a', 'ticket-b'],
    ticket_count: 2,
    requester_count: 2,
    detected_at: '2026-09-18T10:00:00Z',
}

describe('ticketSpikeBannerLogic', () => {
    let logic: ReturnType<typeof ticketSpikeBannerLogic.build>
    let listRequests: number

    function setUpGates(flagEnabled: boolean, settings: Record<string, boolean>): void {
        // Spread the default team so it keeps its id; the loader needs currentTeamId.
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_settings: settings } as unknown as TeamType)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(
            flagEnabled ? [FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_PATTERNS] : [],
            flagEnabled ? { [FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_PATTERNS]: true } : {}
        )
    }

    beforeEach(() => {
        listRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/ticket_patterns/': () => {
                    listRequests += 1
                    return [200, [SPIKE]]
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The flag is the feature's rollout lever. Detection and the settings section both fail closed
    // on it, so a rollback must not leave the banner serving spikes cached before the rollback.
    it.each([
        { name: 'every gate open', flag: true, detection: true, banner: true, expected: true },
        { name: 'the flag rolled back', flag: false, detection: true, banner: true, expected: false },
        { name: 'detection switched off', flag: true, detection: false, banner: true, expected: false },
        { name: 'the banner switched off', flag: true, detection: true, banner: false, expected: false },
    ])('$name -> bannerEnabled $expected', async ({ flag, detection, banner, expected }) => {
        setUpGates(flag, { ticket_patterns_enabled: detection, ticket_patterns_banner_enabled: banner })

        logic = ticketSpikeBannerLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.bannerEnabled).toBe(expected)
        expect(logic.values.spikes).toEqual(expected ? [SPIKE] : [])
        // A closed gate must not send ticket ids to the endpoint at all.
        expect(listRequests).toBe(expected ? 1 : 0)
    })

    // Every dismissal reloads the list. A reload that reads the server before the second
    // dismissal is saved must not bring the second spike back, whichever request lands first.
    it.each([
        { name: 'the first reload lands before the second save', order: ['firstReload', 'secondSave'] as const },
        { name: 'the reloads land in reverse order', order: ['secondSave', 'firstReload'] as const },
    ])('two quick dismissals stay hidden when $name', async ({ order }) => {
        const first = { ...SPIKE, key: 'spike-first' }
        const second = { ...SPIKE, key: 'spike-second', topic: 'Replays do not load' }
        const dismissed = new Set<string>()
        const held = { firstReload: deferred(), secondSave: deferred() }
        const firstReloadArrived = deferred()
        let lists = 0
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/ticket_patterns/': async () => {
                    lists += 1
                    const body = [first, second].map((spike) => ({
                        ...spike,
                        dismissed_by: dismissed.has(spike.key) ? 'A teammate' : null,
                    }))
                    if (lists === 2) {
                        firstReloadArrived.resolve()
                        await held.firstReload.promise
                    }
                    return [200, body]
                },
            },
            post: {
                '/api/projects/:team_id/conversations/ticket_patterns/dismiss/': async ({ request }) => {
                    const { key } = (await request.json()) as { key: string }
                    if (key === second.key) {
                        await held.secondSave.promise
                    }
                    dismissed.add(key)
                    return [204]
                },
            },
        })
        setUpGates(true, { ticket_patterns_enabled: true, ticket_patterns_banner_enabled: true })
        logic = ticketSpikeBannerLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.dismissSpike(first.key)
        await firstReloadArrived.promise
        logic.actions.dismissSpike(second.key)
        expect(logic.values.visibleSpikes).toEqual([])

        const [landsFirst, landsLast] = order
        const reloadAfter = { firstReload: first.key, secondSave: second.key }[landsFirst]
        held[landsFirst].resolve()
        await expectLogic(logic).toDispatchActions([
            (action) =>
                action.type === logic.actionTypes.loadSpikesSuccess &&
                action.payload.spikes.some(
                    (spike: TicketPatternApi) => spike.key === reloadAfter && !!spike.dismissed_by
                ),
        ])
        expect(logic.values.visibleSpikes).toEqual([])

        held[landsLast].resolve()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.visibleSpikes).toEqual([])
        expect(logic.values.dismissedSpikes.map((spike) => spike.key)).toEqual([first.key, second.key])
    })

    // A reload keeps an unconfirmed dismissal hidden, so a failed save has to release it itself.
    it('a dismissal the server rejects shows the spike again', async () => {
        const spike = { ...SPIKE, key: 'spike-first', dismissed_by: null }
        useMocks({
            get: { '/api/projects/:team_id/conversations/ticket_patterns/': () => [200, [spike]] },
            post: { '/api/projects/:team_id/conversations/ticket_patterns/dismiss/': () => [500, {}] },
        })
        setUpGates(true, { ticket_patterns_enabled: true, ticket_patterns_banner_enabled: true })
        logic = ticketSpikeBannerLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.dismissSpike(spike.key)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.visibleSpikes.map((visible) => visible.key)).toEqual([spike.key])
    })
})

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve: () => void = () => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}
