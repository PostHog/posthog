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

const ORGANIZATION_PROPERTIES = `${TaxonomicFilterGroupType.GroupsPrefix}_0` as TaxonomicFilterGroupType

const exampleEvent = (uuid: string, properties: Record<string, unknown>): Record<string, unknown> => ({
    uuid,
    event: 'checkout completed',
    timestamp: '2025-01-01T00:00:00Z',
    distinct_id: 'user-1',
    properties,
})

const examplePerson = (uuid: string, properties: Record<string, unknown>): Record<string, unknown> => ({
    uuid,
    distinct_id: `distinct-${uuid}`,
    created_at: '2024-12-01T00:00:00Z',
    properties,
})

describe('taxonomicExampleBrowserLogic', () => {
    let queryBodies: Record<string, any>[]
    let onChange: jest.Mock

    const baseProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: 'example-browser-test',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            ORGANIZATION_PROPERTIES,
        ],
        eventNames: ['checkout completed'],
        enableKeywordShortcuts: true,
    }

    function buildLogic(
        overrides: Partial<TaxonomicFilterLogicProps> = {},
        activeTab: TaxonomicFilterGroupType = TaxonomicFilterGroupType.EventProperties
    ): ReturnType<typeof taxonomicExampleBrowserLogic.build> {
        const props = { ...baseProps, onChange, ...overrides }
        taxonomicFilterLogic(props).mount()
        taxonomicFilterLogic(props).actions.setActiveTab(activeTab)
        const logic = taxonomicExampleBrowserLogic(props)
        logic.mount()
        return logic
    }

    async function openAndLoad(logic: ReturnType<typeof taxonomicExampleBrowserLogic.build>): Promise<void> {
        await expectLogic(logic, () => logic.actions.openExampleBrowser()).toDispatchActions(['loadExamplesSuccess'])
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
                '/api/projects/:team/groups_types': [
                    { group_type: 'organization', group_type_index: 0, name_singular: null, name_plural: null },
                ],
            },
            post: {
                '/api/environments/:team/query/EventsQuery/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    queryBodies.push(body)
                    if (body.query.select.includes('person')) {
                        return [
                            200,
                            {
                                results: [
                                    [examplePerson('p1', { plan: 'pro', $geoip_city_name: 'Lisbon' }), '2025-01-03'],
                                    [examplePerson('p1', { plan: 'pro', $geoip_city_name: 'Lisbon' }), '2025-01-02'],
                                    [examplePerson('p2', { plan: 'free' }), '2025-01-01'],
                                ],
                            },
                        ]
                    }
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
                '/api/environments/:team/query/HogQLQuery/': async ({ request }) => {
                    queryBodies.push((await request.json()) as Record<string, any>)
                    return [
                        200,
                        {
                            results: [
                                [
                                    'org-1',
                                    JSON.stringify({ name: 'Hogflix', tier: 'enterprise', $group_key: 'org-1' }),
                                    '2025-01-01',
                                ],
                                ['org-2', JSON.stringify({ tier: 'starter' }), '2024-12-31'],
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
        [
            'event properties tab without an event in context',
            TaxonomicFilterGroupType.EventProperties,
            { eventNames: [] },
            false,
        ],
        ['event properties tab with an event in context', TaxonomicFilterGroupType.EventProperties, {}, true],
        ['person properties tab', TaxonomicFilterGroupType.PersonProperties, { eventNames: [] }, true],
        ['group properties tab', ORGANIZATION_PROPERTIES, { eventNames: [] }, true],
        [
            'a tab that is not a property list',
            TaxonomicFilterGroupType.Events,
            { taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.EventProperties] },
            false,
        ],
    ])('is available on the %s: %p', (_, activeTab, overrides, expected) => {
        const logic = buildLogic(overrides, activeTab)
        expect(logic.values.isAvailable).toBe(expected)
    })

    it('is unavailable when the feature flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        expect(buildLogic().values.isAvailable).toBe(false)
    })

    it('loads recent events for the event in context when opened', async () => {
        const logic = buildLogic()
        await openAndLoad(logic)

        expect(queryBodies[0].query).toMatchObject({ kind: 'EventsQuery', event: 'checkout completed', limit: 10 })
        expect(logic.values.currentExample).toMatchObject({ id: 'e1', label: 'checkout completed' })
    })

    it('filters several events in context with a HogQL clause', async () => {
        const logic = buildLogic({ eventNames: ['checkout completed', 'checkout started'] })
        await openAndLoad(logic)

        expect(queryBodies[0].query.event).toBeUndefined()
        expect(queryBodies[0].query.properties).toEqual([
            { type: PropertyFilterType.HogQL, key: "event IN ['checkout completed', 'checkout started']" },
        ])
    })

    it('loads the people behind recent events in context once each, most recent first', async () => {
        const logic = buildLogic({}, TaxonomicFilterGroupType.PersonProperties)
        await openAndLoad(logic)

        expect(queryBodies[0].query).toMatchObject({
            kind: 'EventsQuery',
            select: ['person', 'timestamp'],
            event: 'checkout completed',
        })
        expect(logic.values.examples.map((example) => example.id)).toEqual(['p1', 'p2'])
        expect(logic.values.currentExample).toMatchObject({ label: 'distinct-p1', timestamp: '2025-01-03' })
    })

    it('loads recent groups of the type in context', async () => {
        const logic = buildLogic({}, ORGANIZATION_PROPERTIES)
        await openAndLoad(logic)

        expect(queryBodies[0].query.kind).toBe('HogQLQuery')
        expect(queryBodies[0].query.query).toContain('index = 0')
        expect(logic.values.examples.map((example) => example.label)).toEqual(['Hogflix', 'org-2'])
    })

    it('forgets loaded examples when the tab changes', async () => {
        const logic = buildLogic()
        await openAndLoad(logic)

        taxonomicFilterLogic(logic.props).actions.setActiveTab(TaxonomicFilterGroupType.PersonProperties)

        expect(logic.values.examples).toEqual([])
        expect(logic.values.isOpen).toBe(false)
    })

    it.each([
        ['events', TaxonomicFilterGroupType.EventProperties, ['cart', 'plan']],
        ['people', TaxonomicFilterGroupType.PersonProperties, ['plan']],
        ['groups', ORGANIZATION_PROPERTIES, ['name', 'tier']],
    ])('hides PostHog properties of %s until the user asks for them', async (_, activeTab, customKeys) => {
        const logic = buildLogic({}, activeTab)
        await openAndLoad(logic)

        expect(logic.values.visibleProperties.map(([key]) => key)).toEqual(customKeys)

        logic.actions.setHidePostHogProperties(false)
        expect(logic.values.visibleProperties.length).toBeGreaterThan(customKeys.length)
    })

    it('narrows the properties to the search query', async () => {
        const logic = buildLogic()
        await openAndLoad(logic)

        taxonomicFilterLogic(logic.props).actions.setSearchQuery('pro')
        expect(logic.values.visibleProperties).toEqual([['plan', 'pro']])
    })

    it('pages between examples and stops at both ends', async () => {
        const logic = buildLogic()
        await openAndLoad(logic)

        expect(logic.values.hasPreviousExample).toBe(false)
        expect(logic.values.hasNextExample).toBe(true)

        logic.actions.showNextExample()
        expect(logic.values.currentExample?.id).toBe('e2')
        expect(logic.values.hasNextExample).toBe(false)

        logic.actions.showPreviousExample()
        logic.actions.showPreviousExample()
        expect(logic.values.currentExample?.id).toBe('e1')
    })

    it.each([
        [TaxonomicFilterGroupType.EventProperties, PropertyFilterType.Event, { eventName: 'checkout completed' }],
        [TaxonomicFilterGroupType.PersonProperties, PropertyFilterType.Person, {}],
        [ORGANIZATION_PROPERTIES, PropertyFilterType.Group, { groupTypeIndex: 0 }],
    ])('selects keys and values through the %s group', async (activeTab, propertyFilterType, extra) => {
        const logic = buildLogic({}, activeTab)
        await openAndLoad(logic)

        logic.actions.selectExampleKey('plan')
        expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ type: activeTab }), 'plan', { name: 'plan' })

        logic.actions.selectExampleValue('plan', 'pro')
        expect(onChange).toHaveBeenCalledWith(
            expect.objectContaining({ type: activeTab }),
            'plan',
            expect.objectContaining({
                _type: 'quick_filter',
                propertyKey: 'plan',
                filterValue: 'pro',
                operator: PropertyOperator.Exact,
                propertyFilterType,
                ...extra,
            })
        )
    })

    it('does not select a value when the host cannot handle quick filters', async () => {
        const logic = buildLogic({ enableKeywordShortcuts: false })
        await openAndLoad(logic)

        expect(logic.values.supportsValueSelection).toBe(false)
        logic.actions.selectExampleValue('plan', 'pro')
        expect(onChange).not.toHaveBeenCalled()
    })

    it.each([
        [TaxonomicFilterGroupType.EventProperties, ['/activity/explore', '"event":"checkout completed"']],
        [TaxonomicFilterGroupType.PersonProperties, ['/persons']],
        [ORGANIZATION_PROPERTIES, ['/groups/0']],
    ])('links to the page that explores the %s source', (activeTab, fragments) => {
        const logic = buildLogic({}, activeTab)
        const url = decodeURIComponent(logic.values.exploreUrl ?? '')
        for (const fragment of fragments) {
            expect(url).toContain(fragment)
        }
    })
})
