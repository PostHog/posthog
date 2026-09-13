import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { AppContext, PropertyFilterType, PropertyOperator } from '~/types'

import { taxonomicExampleBrowserLogic } from './taxonomicExampleBrowserLogic'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from './types'

window.POSTHOG_APP_CONTEXT = {
    current_team: { id: MOCK_TEAM_ID },
    current_project: { id: MOCK_TEAM_ID },
} as unknown as AppContext

const exampleEvent = (uuid: string, properties: Record<string, unknown>): Record<string, unknown> => ({
    uuid,
    event: 'checkout completed',
    timestamp: '2025-01-01T00:00:00Z',
    distinct_id: 'user-1',
    properties,
})

describe('taxonomicExampleBrowserLogic', () => {
    let queryBodies: Record<string, any>[]
    let onChange: jest.Mock

    const baseProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: 'example-browser-test',
        taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
        eventNames: ['checkout completed'],
        enableKeywordShortcuts: true,
    }

    function buildLogic(
        overrides: Partial<TaxonomicFilterLogicProps> = {}
    ): ReturnType<typeof taxonomicExampleBrowserLogic.build> {
        const props = { ...baseProps, onChange, ...overrides }
        taxonomicFilterLogic(props).mount()
        const logic = taxonomicExampleBrowserLogic(props)
        logic.mount()
        return logic
    }

    beforeEach(() => {
        queryBodies = []
        onChange = jest.fn()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': { results: [], count: 0 },
                '/api/projects/:team/property_definitions': { results: [], count: 0 },
                '/api/projects/:team/actions/': { results: [], count: 0 },
                '/api/environments/:team/persons/properties': [],
            },
            post: {
                '/api/environments/:team/query/EventsQuery/': async ({ request }) => {
                    queryBodies.push((await request.json()) as Record<string, any>)
                    return [
                        200,
                        {
                            results: [
                                [exampleEvent('e1', { plan: 'pro', $browser: 'Chrome', cart: { items: 2 } })],
                                [exampleEvent('e2', { plan: 'free', $browser: 'Firefox' })],
                            ],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TAXONOMIC_FILTER_EXAMPLE_BROWSER]: true })
    })

    afterEach(() => {
        featureFlagLogic.actions.setFeatureFlags([], {})
    })

    it.each([
        ['no event context', { eventNames: [] }, false],
        ['no event properties group', { taxonomicGroupTypes: [TaxonomicFilterGroupType.PersonProperties] }, false],
        ['event context with event properties group', {}, true],
    ])('is available when there is %s: %p', (_, overrides, expected) => {
        const logic = buildLogic(overrides)
        expect(logic.values.isAvailable).toBe(expected)
    })

    it('is unavailable when the feature flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        expect(buildLogic().values.isAvailable).toBe(false)
    })

    it('loads recent events for the event in context when opened', async () => {
        const logic = buildLogic()
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])

        expect(queryBodies[0].query).toMatchObject({ kind: 'EventsQuery', event: 'checkout completed', limit: 10 })
        expect(logic.values.currentExample?.id).toBe('e1')
    })

    it('filters several events in context with a HogQL clause', async () => {
        const logic = buildLogic({ eventNames: ['checkout completed', 'checkout started'] })
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])

        expect(queryBodies[0].query.event).toBeUndefined()
        expect(queryBodies[0].query.properties).toEqual([
            { type: PropertyFilterType.HogQL, key: "event IN ['checkout completed', 'checkout started']" },
        ])
    })

    it('hides PostHog properties until the user asks for them', async () => {
        const logic = buildLogic()
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])

        expect(logic.values.visibleProperties.map(([key]) => key)).toEqual(['cart', 'plan'])

        logic.actions.setHidePostHogProperties(false)
        expect(logic.values.visibleProperties.map(([key]) => key)).toEqual(['$browser', 'cart', 'plan'])
    })

    it('narrows the properties to the search query', async () => {
        const logic = buildLogic()
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])

        taxonomicFilterLogic(logic.props).actions.setSearchQuery('pro')
        expect(logic.values.visibleProperties).toEqual([['plan', 'pro']])
    })

    it('pages between examples and stops at both ends', async () => {
        const logic = buildLogic()
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])

        expect(logic.values.hasPreviousExample).toBe(false)
        expect(logic.values.hasNextExample).toBe(true)

        logic.actions.showNextExample()
        expect(logic.values.currentExample?.id).toBe('e2')
        expect(logic.values.hasNextExample).toBe(false)

        logic.actions.showPreviousExample()
        logic.actions.showPreviousExample()
        expect(logic.values.currentExample?.id).toBe('e1')
    })

    it('selects the property key through the event properties group', async () => {
        const logic = buildLogic()
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])

        logic.actions.selectExampleKey('plan')

        expect(onChange).toHaveBeenCalledWith(
            expect.objectContaining({ type: TaxonomicFilterGroupType.EventProperties }),
            'plan',
            { name: 'plan' }
        )
    })

    it('selects a value as an exact-match quick filter', async () => {
        const logic = buildLogic()
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])

        logic.actions.selectExampleValue('plan', 'pro')

        expect(onChange).toHaveBeenCalledWith(
            expect.objectContaining({ type: TaxonomicFilterGroupType.EventProperties }),
            'plan',
            expect.objectContaining({
                _type: 'quick_filter',
                propertyKey: 'plan',
                filterValue: 'pro',
                operator: PropertyOperator.Exact,
                propertyFilterType: PropertyFilterType.Event,
                eventName: 'checkout completed',
            })
        )
    })

    it('does not select a value when the host cannot handle quick filters', async () => {
        const logic = buildLogic({ enableKeywordShortcuts: false })
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])

        expect(logic.values.supportsValueSelection).toBe(false)
        logic.actions.selectExampleValue('plan', 'pro')
        expect(onChange).not.toHaveBeenCalled()
    })

    it('links to the activity page filtered to the event in context', () => {
        const logic = buildLogic()
        const url = decodeURIComponent(logic.values.exploreUrl ?? '')
        expect(url).toContain('/activity/explore')
        expect(url).toContain('"event":"checkout completed"')
    })
})
