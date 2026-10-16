import { MOCK_TEAM_ID } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { resetEventMatchMemoryForTests, taxonomicEventMatchLogic } from './taxonomicEventMatchLogic'
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

const ELIGIBLE_EVENT = 'taxonomic filter event match eligible'

const AUTOCAPTURE = { name: '$autocapture', display_name: 'Autocapture', probability: 0.95 }

describe('taxonomicEventMatchLogic', () => {
    let filterLogic: ReturnType<typeof taxonomicFilterLogic.build>
    let logic: ReturnType<typeof taxonomicEventMatchLogic.build>
    let matchRequests: Record<string, any>[]
    let status: number
    let matches: Record<string, any>[]
    let outcome: string
    let unsent: Record<string, any>[]
    let answerGate: Promise<void> | null

    beforeEach(() => {
        matchRequests = []
        status = 200
        matches = [AUTOCAPTURE]
        outcome = 'matched'
        unsent = []
        answerGate = null
        resetEventMatchMemoryForTests()
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
                    return status === 200 ? [200, { matches, outcome, unsent }] : [status, {}]
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

    const enroll = (variant: 'test' | 'control' | false): void => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_EVENT_MATCH], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_EVENT_MATCH]: variant,
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

    const holdAnswer = (): (() => void) => {
        let answer: () => void = () => {}
        answerGate = new Promise<void>((resolve) => {
            answer = resolve
        })
        return answer
    }

    it.each([
        ['for a person outside the flag', (): typeof logic => (enroll(false), logic)],
        ['for a person in the control arm', (): typeof logic => (enroll('control'), logic)],
        [
            'from a tab that never shows suggestions',
            (): typeof logic => {
                enroll('test')
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
        expect(askedLogic.values.isMatching).toBe(false)

        await expectLogic(askedLogic).toFinishAllListeners()

        expect(matchRequests).toHaveLength(0)
        expect(askedLogic.values.isMatching).toBe(false)
        expect(askedLogic.values.suggestedEvents).toEqual([])
    })

    it.each([
        ['during the pause', async (): Promise<void> => {}, 0],
        [
            'while the model answers',
            async (): Promise<void> => {
                await waitFor(() => expect(matchRequests).toHaveLength(1))
            },
            1,
        ],
    ])('drops the ask when another tab opens %s', async (_, waitBeforeSwitch, expectedRequests) => {
        enroll('test')
        const captureSpy = jest.spyOn(posthog, 'capture')
        const answer = holdAnswer()
        const { allTabFilterLogic, allTabLogic } = mountAllTabPicker()

        allTabFilterLogic.actions.setSearchQuery('browser capture')
        await waitBeforeSwitch()
        allTabFilterLogic.actions.setActiveTab(TaxonomicFilterGroupType.Actions)
        answer()
        await expectLogic(allTabLogic).toFinishAllListeners()

        expect(matchRequests).toHaveLength(expectedRequests)
        expect(allTabLogic.values.isMatching).toBe(false)
        expect(allTabLogic.values.suggestedEvents).toEqual([])
        expect(captureSpy).not.toHaveBeenCalledWith('taxonomic filter event match suggested', expect.anything())
        // Exposure counts only once the pause ended on a visible list.
        expect(captureSpy.mock.calls.filter(([event]) => event === ELIGIBLE_EVENT)).toHaveLength(expectedRequests)
    })

    it('shows a loading state from the All tab until the answer arrives, and records the tab', async () => {
        enroll('test')
        const captureSpy = jest.spyOn(posthog, 'capture')
        const answer = holdAnswer()
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
        enroll('test')
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

    it('shows the remembered answer again when the empty state remounts for the same search', async () => {
        enroll('test')
        const captureSpy = jest.spyOn(posthog, 'capture')
        await search('browser capture')
        expect(matchRequests).toHaveLength(1)

        logic.unmount()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(matchRequests).toHaveLength(1)
        expect(logic.values.isMatching).toBe(false)
        expect(logic.values.suggestedEvents).toEqual([AUTOCAPTURE])
        const suggestedCaptures = captureSpy.mock.calls.filter(
            ([event]) => event === 'taxonomic filter event match suggested'
        )
        expect(suggestedCaptures).toHaveLength(2)
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
        enroll('test')
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
        enroll('test')
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
        enroll('test')
        status = 404

        const captureSpy = jest.spyOn(posthog, 'capture')

        await search('browser capture')
        await search('page view')

        expect(matchRequests).toHaveLength(1)
        expect(logic.values.suggestedEvents).toEqual([])
        expect(logic.values.isMatching).toBe(false)
        // A 404 must not make the test arm look less exposed than control.
        expect(captureSpy.mock.calls.filter(([event]) => event === ELIGIBLE_EVENT)).toHaveLength(2)
    })

    it.each([
        [404, false],
        [429, false],
        [503, false],
        [500, true],
    ])('reports a %s failure to error tracking: %s', async (failureStatus, reported) => {
        enroll('test')
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

    it.each([['control'], ['test']] as const)(
        'reports the %s arm as eligible once per search, after the pause',
        async (variant) => {
            enroll(variant)
            const captureSpy = jest.spyOn(posthog, 'capture')

            // A prefix typed before the pause ends must not count as a search.
            filterLogic.actions.setSearchQuery('browser')
            await search('browser capture')
            logic.unmount()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const eligible = captureSpy.mock.calls.filter(([event]) => event === ELIGIBLE_EVENT)
            expect(eligible).toEqual([
                ['taxonomic filter event match eligible', { surface: 'legacy-pill', tab: 'events', variant }],
            ])
            expect(matchRequests).toHaveLength(variant === 'test' ? 1 : 0)
        }
    )

    it('names the likely events the project never sent instead of suggesting them', async () => {
        enroll('test')
        matches = []
        outcome = 'not_ingested'
        unsent = [{ name: '$screen', display_name: 'Screen', probability: 0.85 }]
        const captureSpy = jest.spyOn(posthog, 'capture')

        await search('mobile screen')

        expect(logic.values.suggestedEvents).toEqual([])
        expect(logic.values.hint).toEqual({ kind: 'unsent', events: unsent })
        expect(captureSpy).toHaveBeenCalledWith('taxonomic filter event match hint shown', {
            surface: 'legacy-pill',
            tab: 'events',
            hint: 'unsent',
            unsentEvents: ['$screen'],
        })
    })

    it('does not name an unsent event the picker excludes', async () => {
        const excludingProps: TaxonomicFilterLogicProps = {
            ...PROPS,
            taxonomicFilterLogicKey: 'event-match-excluding-unsent-test',
            excludedProperties: { [TaxonomicFilterGroupType.Events]: ['$screen'] },
        }
        const excludingFilterLogic = taxonomicFilterLogic(excludingProps)
        excludingFilterLogic.mount()
        const excludingLogic = taxonomicEventMatchLogic(excludingProps)
        excludingLogic.mount()
        enroll('test')
        matches = []
        outcome = 'not_ingested'
        unsent = [{ name: '$screen', display_name: 'Screen', probability: 0.85 }]

        excludingFilterLogic.actions.setSearchQuery('mobile screen')
        await expectLogic(excludingLogic).toFinishAllListeners()

        expect(excludingLogic.values.hint).toBeNull()
    })

    it.each([
        { picker: 'events only', taxonomicGroupTypes: [TaxonomicFilterGroupType.Events], hint: null },
        {
            picker: 'events and event properties',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.EventProperties],
            hint: { kind: 'value' },
        },
        {
            picker: 'events and person properties',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.PersonProperties],
            hint: { kind: 'value' },
        },
        {
            picker: 'events and session properties',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.SessionProperties],
            hint: { kind: 'value' },
        },
    ])(
        'points a value search at properties only where one can be picked: $picker',
        async ({ taxonomicGroupTypes, hint }) => {
            enroll('test')
            matches = []
            outcome = 'only_values'
            const pickerProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: `event-match-value-hint-${taxonomicGroupTypes.join('-')}`,
                taxonomicGroupTypes,
            }
            const pickerFilterLogic = taxonomicFilterLogic(pickerProps)
            pickerFilterLogic.mount()
            const pickerLogic = taxonomicEventMatchLogic(pickerProps)
            pickerLogic.mount()
            pickerFilterLogic.actions.setActiveTab(TaxonomicFilterGroupType.Events)

            pickerFilterLogic.actions.setSearchQuery('ada@example.com')
            await expectLogic(pickerLogic).toFinishAllListeners()

            expect(pickerLogic.values.hint).toEqual(hint)
        }
    )

    it('shows no hint when the model simply found nothing likely', async () => {
        enroll('test')
        matches = []
        outcome = 'nothing_likely'

        await search('browser capture')

        expect(logic.values.hint).toBeNull()
    })
})
