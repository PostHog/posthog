import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

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
})
