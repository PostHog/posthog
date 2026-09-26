import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { resetEventMatchAvailabilityForTests, taxonomicEventMatchLogic } from './taxonomicEventMatchLogic'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from './types'

window.POSTHOG_APP_CONTEXT = {
    current_team: { id: MOCK_TEAM_ID },
    current_project: { id: MOCK_TEAM_ID },
} as unknown as AppContext

const PROPS: TaxonomicFilterLogicProps = {
    taxonomicFilterLogicKey: 'event-match-test',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
}

const AUTOCAPTURE = { name: '$autocapture', display_name: 'Autocapture', probability: 0.95 }

describe('taxonomicEventMatchLogic', () => {
    let filterLogic: ReturnType<typeof taxonomicFilterLogic.build>
    let logic: ReturnType<typeof taxonomicEventMatchLogic.build>
    let matchRequests: Record<string, any>[]
    let status: number

    beforeEach(() => {
        matchRequests = []
        status = 200
        resetEventMatchAvailabilityForTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': () => [200, { results: [], count: 0 }],
            },
            post: {
                '/api/projects/:team/taxonomic_search_intent/match_events/': async ({ request }) => {
                    matchRequests.push((await request.json()) as Record<string, any>)
                    return status === 200 ? [200, { matches: [AUTOCAPTURE] }] : [status, {}]
                },
            },
        })
        initKeaTests()
        filterLogic = taxonomicFilterLogic(PROPS)
        filterLogic.mount()
        logic = taxonomicEventMatchLogic(PROPS)
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const search = async (query: string): Promise<void> => {
        filterLogic.actions.setSearchQuery(query)
        await expectLogic(logic).toFinishAllListeners()
    }

    const enroll = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_EVENT_MATCH], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_EVENT_MATCH]: enabled,
        })
    }

    it('does not ask the model for a person outside the flag', async () => {
        enroll(false)

        await search('browser capture')

        expect(matchRequests).toHaveLength(0)
        expect(logic.values.suggestedEvents).toEqual([])
    })

    it('suggests the matched events for the current search only, and selects one on click', async () => {
        enroll(true)
        const captureSpy = jest.spyOn(posthog, 'capture')

        await search('browser capture')

        expect(matchRequests).toEqual([{ query: 'browser capture' }])
        expect(logic.values.suggestedEvents).toEqual([AUTOCAPTURE])

        await expectLogic(filterLogic, () => logic.actions.selectEventMatch(AUTOCAPTURE)).toDispatchActions([
            (action) =>
                action.type === filterLogic.actionTypes.selectItem &&
                action.payload.group.type === TaxonomicFilterGroupType.Events &&
                action.payload.value === '$autocapture' &&
                action.payload.meta.position === 0,
        ])
        expect(captureSpy).toHaveBeenCalledWith('taxonomic filter event match selected', {
            surface: 'legacy-pill',
            eventName: '$autocapture',
            position: 0,
        })

        filterLogic.actions.setSearchQuery('browser capture events')
        expect(logic.values.suggestedEvents).toEqual([])
    })

    it('does not suggest an event the picker excludes', async () => {
        const excludingProps: TaxonomicFilterLogicProps = {
            ...PROPS,
            taxonomicFilterLogicKey: 'event-match-excluding-test',
            excludedProperties: { [TaxonomicFilterGroupType.Events]: ['$autocapture'] },
        }
        const excludingFilterLogic = taxonomicFilterLogic(excludingProps)
        excludingFilterLogic.mount()
        const excludingLogic = taxonomicEventMatchLogic(excludingProps)
        excludingLogic.mount()
        enroll(true)

        excludingFilterLogic.actions.setSearchQuery('browser capture')
        await expectLogic(excludingLogic).toFinishAllListeners()

        expect(matchRequests).toHaveLength(1)
        expect(excludingLogic.values.suggestedEvents).toEqual([])
    })

    it('stops asking for the project after a 404', async () => {
        enroll(true)
        status = 404

        await search('browser capture')
        await search('page view')

        expect(matchRequests).toHaveLength(1)
        expect(logic.values.suggestedEvents).toEqual([])
    })
})
