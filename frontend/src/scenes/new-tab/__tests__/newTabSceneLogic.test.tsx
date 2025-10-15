import { expectLogic } from 'kea-test-utils'
import type { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { newTabSceneLogic } from '../newTabSceneLogic'

jest.mock(
    '@posthog/hogvm',
    () => ({
        __esModule: true,
        exec: jest.fn(),
        execAsync: jest.fn(() => Promise.resolve({})),
    }),
    { virtual: true }
)

if (!Array.prototype.toSorted) {
    // eslint-disable-next-line no-extend-native
    Array.prototype.toSorted = function toSorted(compareFn) {
        return [...this].sort(compareFn)
    }
}

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        fileSystem: {
            list: jest.fn(() => Promise.resolve({ results: [], hasMore: false })),
        },
        persons: {
            determineListUrl: jest.fn(() => '/api/persons/'),
        },
        eventDefinitions: {
            list: jest.fn(() =>
                Promise.resolve({
                    count: 1,
                    next: null,
                    results: [
                        {
                            id: 1,
                            name: 'pageview',
                        },
                    ],
                })
            ),
        },
        propertyDefinitions: {
            list: jest.fn(() =>
                Promise.resolve({
                    count: 1,
                    next: null,
                    results: [
                        {
                            id: 2,
                            name: 'email',
                        },
                    ],
                })
            ),
        },
        get: jest.fn(() => Promise.resolve({ count: 0, next: null, results: [] })),
    },
}))

jest.mock('~/layout/panel-layout/ProjectTree/defaultTree', () => {
    return {
        __esModule: true,
        ProductIconWrapper: ({ children }: { children: ReactNode }) => <>{children}</>,
        getDefaultTreeNew: () => [
            { path: 'Insight/Dashboard', href: '/insights/dashboard', type: 'insight', flag: null },
            { path: 'Data/Experiment', href: '/data/experiment', type: 'data', flag: null },
        ],
        getDefaultTreeProducts: () => [
            { path: 'Apps/Dashboard', href: '/apps/dashboard', type: 'dashboard', flag: null },
        ],
        getDefaultTreePersons: () => [
            { path: 'Persons/Directory', href: '/persons/directory', type: 'person', flag: null },
        ],
        getDefaultTreeData: () => [
            {
                path: 'Events/Event A',
                href: '/data/events/event-a',
                type: 'event_definition',
                iconType: 'event_definition',
            },
            {
                path: 'Properties/Property A',
                href: '/data/properties/property-a',
                type: 'property_definition',
                iconType: 'property_definition',
            },
        ],
        iconForType: () => null,
    }
})

jest.mock('~/layout/panel-layout/ProjectTree/projectTreeDataLogic', () => {
    const { kea } = require('kea')
    const staticItems = [
        {
            id: 'project://',
            name: 'Project',
            record: { protocol: 'project://', path: '' },
            children: [
                {
                    id: 'project://dashboards',
                    name: 'dashboards',
                    record: { protocol: 'project://', path: 'dashboards' },
                },
                {
                    id: 'apps://dashboards',
                    name: 'apps dashboards',
                    record: { protocol: 'apps://', path: 'dashboards' },
                },
            ],
        },
        {
            id: 'apps://',
            name: 'Apps',
            record: { protocol: 'apps://', path: '' },
            children: [],
        },
        {
            id: 'data://',
            name: 'Data',
            record: { protocol: 'data://', path: '' },
            children: [
                { id: 'events://insights', name: 'events', record: { protocol: 'events://', path: 'events' } },
                {
                    id: 'properties://properties',
                    name: 'properties',
                    record: { protocol: 'properties://', path: 'properties' },
                },
            ],
        },
        {
            id: 'persons://',
            name: 'Persons',
            record: { protocol: 'persons://', path: '' },
            children: [],
        },
        {
            id: 'shortcuts://',
            name: 'Shortcuts',
            record: { protocol: 'shortcuts://', path: '' },
            children: [],
        },
        {
            id: 'new://',
            name: 'Create new',
            record: { protocol: 'new://', path: '' },
            children: [],
        },
    ]

    return {
        __esModule: true,
        projectTreeDataLogic: kea({
            path: ['scenes', 'new-tab', 'tests', 'projectTreeDataLogic'],
            selectors: {
                getStaticTreeItems: [() => [], () => () => staticItems],
            },
        }),
    }
})

describe('newTabSceneLogic', () => {
    let logic: ReturnType<typeof newTabSceneLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests(false)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]: true,
        })
        logic = newTabSceneLogic({ tabId: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('builds destination options including ask://', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.destinationOptions.map((option) => option.value)).toEqual([
            'project://',
            'apps://',
            'data://',
            'events://',
            'properties://',
            'persons://',
            'shortcuts://',
            'new://',
            'ask://',
        ])
    })

    it('filters grid items by selected destinations', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSelectedDestinations(['events://'])
        }).toFinishAllListeners()

        expect(logic.values.filteredItemsGrid.length).toBeGreaterThan(0)
        expect(
            logic.values.filteredItemsGrid.every((item) => (item.protocol ?? '').toLowerCase() === 'events://')
        ).toBe(true)
    })

    it('treats ask:// as an exclusive selection and omits it from sections', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSelectedDestinations(['ask://', 'properties://'])
        }).toFinishAllListeners()

        expect(logic.values.selectedDestinations).toEqual(['ask://'])
        const sectionKeys = logic.values.destinationSections.map(([key]) => key)
        expect(sectionKeys).toContain('properties://')
        expect(sectionKeys).not.toContain('ask://')
    })

    it('toggles person search mode when selecting persons destination', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSelectedDestinations(['persons://'])
        })
            .toMatchValues({
                newTabSceneDataIncludePersons: true,
                specialSearchMode: 'persons',
            })
            .toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setSelectedDestinations([])
        })
            .toMatchValues({
                newTabSceneDataIncludePersons: false,
                specialSearchMode: null,
            })
            .toFinishAllListeners()
    })

    it('prioritizes persons when searching by email address', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSearch('user@example.com')
        })
            .toMatchValues({
                newTabSceneDataIncludePersons: true,
            })
            .toFinishAllListeners()

        expect(logic.values.destinationSections[0]?.[0]).toEqual('persons://')
    })
})
