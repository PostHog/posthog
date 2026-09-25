import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { resetSearchIntentAvailabilityForTests, taxonomicSearchIntentLogic } from './taxonomicSearchIntentLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from './types'

window.POSTHOG_APP_CONTEXT = {
    current_team: { id: MOCK_TEAM_ID },
    current_project: { id: MOCK_TEAM_ID },
} as unknown as AppContext

const PROPS: TaxonomicFilterLogicProps = {
    taxonomicFilterLogicKey: 'search-intent-test',
    taxonomicGroupTypes: [
        TaxonomicFilterGroupType.SuggestedFilters,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
    ],
}

const PERSON_PROPERTIES_ANSWER = {
    group_type: 'person_properties',
    confidence: 0.9,
    is_confident: true,
    suggests_switch: true,
    method: 'model',
}

describe('taxonomicSearchIntentLogic', () => {
    let filterLogic: ReturnType<typeof taxonomicFilterLogic.build>
    let logic: ReturnType<typeof taxonomicSearchIntentLogic.build>
    let classifyRequests: Record<string, any>[]
    let answer: Record<string, any>

    beforeEach(() => {
        classifyRequests = []
        answer = PERSON_PROPERTIES_ANSWER
        resetSearchIntentAvailabilityForTests()
        useMocks({
            get: {
                '/api/projects/:team/property_definitions': () => [200, { results: [], count: 0 }],
                '/api/environments/:team/sessions/property_definitions': () => [200, { results: [], count: 0 }],
                '/api/projects/:team/event_definitions': () => [200, { results: [], count: 0 }],
            },
            post: {
                '/api/projects/:team/ml_inference/search_intent/classify/': async ({ request }) => {
                    classifyRequests.push((await request.json()) as Record<string, any>)
                    return [200, answer]
                },
            },
        })
        initKeaTests()
        filterLogic = taxonomicFilterLogic(PROPS)
        filterLogic.mount()
        logic = taxonomicSearchIntentLogic(PROPS)
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const search = async (query: string): Promise<void> => {
        filterLogic.actions.setSearchQuery(query)
        await expectLogic(logic).toFinishAllListeners()
    }

    const enroll = (variant: string | false): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_SEARCH_INTENT], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_SEARCH_INTENT]: variant,
        })
    }

    it('does not ask the model for a person outside the experiment', async () => {
        enroll(false)
        filterLogic.actions.setActiveTab(TaxonomicFilterGroupType.EventProperties)

        await search('email')

        expect(classifyRequests).toHaveLength(0)
        expect(logic.values.intent).toBeNull()
    })

    it('suggests the tab in the banner arm and switches to it on accept', async () => {
        enroll('banner')
        const captureSpy = jest.spyOn(posthog, 'capture')
        filterLogic.actions.setActiveTab(TaxonomicFilterGroupType.EventProperties)

        await search('email')

        expect(classifyRequests).toEqual([
            expect.objectContaining({ query: 'email', active_group_type: 'event_properties' }),
        ])
        expect(logic.values.suggestedSwitch).toEqual({
            groupType: TaxonomicFilterGroupType.PersonProperties,
            groupName: 'Person properties',
        })

        logic.actions.acceptSuggestedSwitch()

        expect(filterLogic.values.activeTab).toEqual(TaxonomicFilterGroupType.PersonProperties)
        expect(logic.values.suggestedSwitch).toBeNull()
        expect(captureSpy).toHaveBeenCalledWith('taxonomic filter search intent switched', {
            surface: 'legacy-pill',
            fromGroupType: 'event_properties',
            toGroupType: 'person_properties',
        })
    })

    it('drops the suggestion as soon as the search changes', async () => {
        enroll('banner')
        filterLogic.actions.setActiveTab(TaxonomicFilterGroupType.EventProperties)
        await search('email')

        filterLogic.actions.setSearchQuery('emails sent')

        expect(logic.values.suggestedSwitch).toBeNull()
    })

    it('records the answer in the control arm without changing the picker', async () => {
        enroll('control')
        const captureSpy = jest.spyOn(posthog, 'capture')
        filterLogic.actions.setActiveTab(TaxonomicFilterGroupType.EventProperties)

        await search('email')

        expect(logic.values.suggestedSwitch).toBeNull()
        expect(filterLogic.values.suggestedFilterGroupOrder[0]).toEqual(TaxonomicFilterGroupType.EventProperties)
        expect(captureSpy).toHaveBeenCalledWith(
            'taxonomic filter search intent predicted',
            expect.objectContaining({
                variant: 'control',
                predictedGroupType: 'person_properties',
                suggestsSwitch: true,
                wouldPromote: true,
                shown: false,
            })
        )
    })

    it.each([
        ['before the results reveal', TaxonomicFilterGroupType.PersonProperties, false],
        ['after the results reveal', TaxonomicFilterGroupType.EventProperties, true],
    ])('in the promote arm, an answer that lands %s puts %s first', async (_, first, revealed) => {
        enroll('promote')
        filterLogic.actions.setSearchQuery('email')
        if (revealed) {
            filterLogic.actions.openRevealBarrier()
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(filterLogic.values.suggestedFilterGroupOrder[0]).toEqual(first)
    })

    it('stops asking after the project turns out not to be enrolled', async () => {
        enroll('banner')
        useMocks({
            post: {
                '/api/projects/:team/ml_inference/search_intent/classify/': async ({ request }) => {
                    classifyRequests.push((await request.json()) as Record<string, any>)
                    return [404, { detail: 'Not found.' }]
                },
            },
        })

        await search('email')
        await search('url')

        expect(classifyRequests).toHaveLength(1)
    })
})
