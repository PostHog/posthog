import { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { QuickFilterKind, SavedInsightsFilters } from './SavedInsightsFilters'
import { SavedInsightFilters } from './savedInsightsLogic'

const defaultFilters: SavedInsightFilters = {
    order: '-last_modified_at',
    tab: 'all' as any,
    search: '',
    insightType: 'All types',
    createdBy: 'All users',
    tags: undefined,
    dateFrom: 'all',
    dateTo: undefined,
    createdDateFrom: undefined,
    createdDateTo: undefined,
    lastViewedDateFrom: undefined,
    lastViewedDateTo: undefined,
    page: 1,
    dashboardId: undefined,
    events: undefined,
    hideFeatureFlagInsights: false,
    favorited: false,
}

const meta: Meta<typeof SavedInsightsFilters> = {
    title: 'Scenes-App/Saved Insights/Filters',
    component: SavedInsightsFilters,
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:id/members/': {
                    results: [
                        {
                            id: '1',
                            user: {
                                id: 1,
                                uuid: 'u1',
                                first_name: 'Jane',
                                last_name: 'Doe',
                                email: 'jane@posthog.com',
                            },
                        },
                        {
                            id: '2',
                            user: {
                                id: 2,
                                uuid: 'u2',
                                first_name: 'John',
                                last_name: 'Smith',
                                email: 'john@posthog.com',
                            },
                        },
                    ],
                },
            },
        }),
    ],
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<{ quickFilters?: QuickFilterKind[]; initialFilters?: Partial<SavedInsightFilters> }> = ({
    quickFilters,
    initialFilters,
}) => {
    const [filters, setFilters] = useState<SavedInsightFilters>({ ...defaultFilters, ...initialFilters })
    return (
        <div className="bg-surface-secondary p-4 rounded">
            <SavedInsightsFilters
                filters={filters}
                setFilters={(partial) => setFilters((prev) => ({ ...prev, ...partial }))}
                quickFilters={quickFilters}
            />
        </div>
    )
}

export const AllFilters = Template.bind({})
AllFilters.args = {}
AllFilters.parameters = { docs: { description: { story: 'Default: all quick filters shown (main insights page).' } } }

export const ModalFilters = Template.bind({})
ModalFilters.args = { quickFilters: ['insightType', 'tags', 'createdBy'] }
ModalFilters.parameters = {
    docs: { description: { story: 'Modal variant: only insight type, tags, and created by filters.' } },
}

export const SearchOnly = Template.bind({})
SearchOnly.args = { quickFilters: [] }
SearchOnly.parameters = { docs: { description: { story: 'Search only, no quick filters.' } } }

export const WithActiveFilters = Template.bind({})
WithActiveFilters.args = {
    quickFilters: ['insightType', 'tags', 'createdBy'],
    initialFilters: { insightType: 'TRENDS', createdBy: [1] },
}
WithActiveFilters.parameters = {
    docs: { description: { story: 'Modal variant with some filters already active.' } },
}
