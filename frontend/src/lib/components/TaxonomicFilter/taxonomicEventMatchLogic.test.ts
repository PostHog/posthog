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

// Two groups, so the picker also offers the "All" tab and opens on it.
const ALL_TAB_PROPS: TaxonomicFilterLogicProps = {
    taxonomicFilterLogicKey: 'event-match-all-tab-test',
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
}

const AUTOCAPTURE = { name: '$autocapture', display_name: 'Autocapture', probability: 0.95 }

describe('taxonomicEventMatchLogic', () => {
    let filterLogic: ReturnType<typeof taxonomicFilterLogic.build>
    let logic: ReturnType<typeof taxonomicEventMatchLogic.build>
    let matchRequests: Record<string, any>[]
    let status: number
    let matches: Record<string, any>[]
    let answerGate: Promise<void> | null

    beforeEach(() => {
        matchRequests = []
        status = 200
        matches = [AUTOCAPTURE]
        answerGate = null
        resetEventMatchAvailabilityForTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': () => [200, { results: [], count: 0 }],
            },
            post: {
                '/api/projects/:team/taxonomic_search_intent/match_events/': async ({ request }) => {
                    matchRequests.push((await request.json()) as Record<string, any>)
                    if (answerGate) {
                        await answerGate
                    }
                    return status === 200 ? [200, { matches }] : [status, {}]
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

    const mountAllTabPicker = (): {
        allTabFilterLogic: ReturnType<typeof taxonomicFilterLogic.build>
        allTabLogic: ReturnType<typeof taxonomicEventMatchLogic.build>
    } => {
        const allTabFilterLogic = taxonomicFilterLogic(ALL_TAB_PROPS)
        allTabFilterLogic.mount()
        const allTabLogic = taxonomicEventMatchLogic(ALL_TAB_PROPS)
        allTabLogic.mount()
        return { allTabFilterLogic, allTabLogic }
    }

    it.each([
        ['for a person outside the flag', (): typeof logic => (enroll(false), logic)],
        [
            'from a tab that never shows suggestions',
            (): typeof logic => {
                enroll(true)
                const { allTabFilterLogic, allTabLogic } = mountAllTabPicker()
                allTabFilterLogic.actions.setActiveTab(TaxonomicFilterGroupType.Actions)
                allTabFilterLogic.actions.setSearchQuery('browser capture')
                return allTabLogic
            },
        ],
    ])('does not ask the model %s', async (_, arrange) => {
        const askedLogic = arrange()
        if (askedLogic === logic) {
            filterLogic.actions.setSearchQuery('browser capture')
        }

        await expectLogic(askedLogic).toFinishAllListeners()

        expect(matchRequests).toHaveLength(0)
        expect(askedLogic.values.isMatching).toBe(false)
        expect(askedLogic.values.suggestedEvents).toEqual([])
    })

    it('shows a loading state from the All tab until the answer arrives, and records the tab', async () => {
        enroll(true)
        const captureSpy = jest.spyOn(posthog, 'capture')
        let answer: () => void = () => {}
        answerGate = new Promise<void>((resolve) => {
            answer = resolve
        })
        const { allTabFilterLogic, allTabLogic } = mountAllTabPicker()
        expect(allTabFilterLogic.values.activeTab).toEqual(TaxonomicFilterGroupType.SuggestedFilters)

        allTabFilterLogic.actions.setSearchQuery('browser capture')
        await expectLogic(allTabLogic).toDispatchActions(['startEventMatch'])

        expect(allTabLogic.values.isMatching).toBe(true)
        expect(allTabLogic.values.suggestedEvents).toEqual([])

        answer()
        await expectLogic(allTabLogic).toFinishAllListeners()

        expect(allTabLogic.values.isMatching).toBe(false)
        expect(allTabLogic.values.suggestedEvents).toEqual([AUTOCAPTURE])
        expect(captureSpy).toHaveBeenCalledWith('taxonomic filter event match suggested', {
            surface: 'legacy-pill',
            tab: 'suggested_filters',
            suggestedEvents: ['$autocapture'],
        })
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
            tab: 'events',
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
        const captureSpy = jest.spyOn(posthog, 'capture')

        excludingFilterLogic.actions.setSearchQuery('browser capture')
        await expectLogic(excludingLogic).toFinishAllListeners()

        expect(matchRequests).toHaveLength(1)
        expect(excludingLogic.values.suggestedEvents).toEqual([])
        expect(captureSpy).not.toHaveBeenCalledWith('taxonomic filter event match suggested', expect.anything())
    })

    it('fills the suggestions from the events the picker does not exclude', async () => {
        const excludingProps: TaxonomicFilterLogicProps = {
            ...PROPS,
            taxonomicFilterLogicKey: 'event-match-limit-test',
            excludedProperties: { [TaxonomicFilterGroupType.Events]: ['$autocapture'] },
        }
        const excludingFilterLogic = taxonomicFilterLogic(excludingProps)
        excludingFilterLogic.mount()
        const excludingLogic = taxonomicEventMatchLogic(excludingProps)
        excludingLogic.mount()
        enroll(true)
        matches = [
            AUTOCAPTURE,
            { name: '$rageclick', display_name: 'Rageclick', probability: 0.9 },
            { name: '$dead_click', display_name: 'Dead click', probability: 0.85 },
            { name: '$pageview', display_name: 'Pageview', probability: 0.8 },
            { name: '$exception', display_name: 'Exception', probability: 0.75 },
        ]

        excludingFilterLogic.actions.setSearchQuery('browser capture')
        await expectLogic(excludingLogic).toFinishAllListeners()

        expect(excludingLogic.values.suggestedEvents.map((match) => match.name)).toEqual([
            '$rageclick',
            '$dead_click',
            '$pageview',
        ])
    })

    it('stops asking for the project after a 404', async () => {
        enroll(true)
        status = 404

        await search('browser capture')
        await search('page view')

        expect(matchRequests).toHaveLength(1)
        expect(logic.values.suggestedEvents).toEqual([])
    })

    it.each([
        [404, false],
        [429, false],
        [503, false],
        [500, true],
    ])('reports a %s failure to error tracking: %s', async (failureStatus, reported) => {
        enroll(true)
        status = failureStatus
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)

        await search('browser capture')

        expect(logic.values.suggestedEvents).toEqual([])
        expect(captureExceptionSpy.mock.calls).toEqual(
            reported
                ? [[expect.anything(), { feature: 'taxonomic-event-match', projectId: MOCK_TEAM_ID, status: 500 }]]
                : []
        )
    })
})
