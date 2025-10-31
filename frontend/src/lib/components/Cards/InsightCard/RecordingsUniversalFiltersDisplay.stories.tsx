import { Meta, StoryFn } from '@storybook/react'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

import { RecordingsUniversalFiltersDisplay as RecordingsUniversalFiltersDisplayComponent } from './RecordingsUniversalFiltersDisplay'

const meta: Meta = {
    title: 'Components/Cards/Recordings Universal Filters Display',
    component: RecordingsUniversalFiltersDisplayComponent,
}
export default meta

const Template: StoryFn<{ filters: RecordingUniversalFilters }> = ({ filters }) => {
    return (
        <div className="bg-surface-primary w-[24rem] p-4 rounded">
            <RecordingsUniversalFiltersDisplayComponent filters={filters} />
        </div>
    )
}

export const BasicDateRange = Template.bind({})
BasicDateRange.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
    },
}

export const CustomDateRange = Template.bind({})
CustomDateRange.args = {
    filters: {
        date_from: '2024-01-01',
        date_to: '2024-01-31',
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
    },
}

export const WithDurationFilter = Template.bind({})
WithDurationFilter.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [
            {
                type: PropertyFilterType.Recording,
                key: 'duration',
                value: 60,
                operator: PropertyOperator.GreaterThan,
            },
        ],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
    },
}

export const WithMultipleDurationFilters = Template.bind({})
WithMultipleDurationFilters.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [
            {
                type: PropertyFilterType.Recording,
                key: 'duration',
                value: 30,
                operator: PropertyOperator.GreaterThan,
            },
            {
                type: PropertyFilterType.Recording,
                key: 'duration',
                value: 300,
                operator: PropertyOperator.LessThan,
            },
        ],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
    },
}

export const WithPropertyFilters = Template.bind({})
WithPropertyFilters.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: PropertyFilterType.Event,
                    key: 'browser',
                    value: ['Chrome', 'Firefox'],
                    operator: PropertyOperator.Exact,
                },
                {
                    type: PropertyFilterType.Person,
                    key: 'email',
                    value: 'user@example.com',
                    operator: PropertyOperator.IContains,
                },
            ],
        },
    },
}

export const WithOrFilters = Template.bind({})
WithOrFilters.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.Or,
            values: [
                {
                    type: PropertyFilterType.Event,
                    key: 'browser',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                },
                {
                    type: PropertyFilterType.Event,
                    key: 'browser',
                    value: 'Safari',
                    operator: PropertyOperator.Exact,
                },
            ],
        },
    },
}

export const WithCohortFilter = Template.bind({})
WithCohortFilter.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: PropertyFilterType.Cohort,
                    key: 'id',
                    value: 1,
                    operator: PropertyOperator.In,
                },
            ],
        },
    },
}

export const WithTestAccountsExcluded = Template.bind({})
WithTestAccountsExcluded.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
        filter_test_accounts: true,
    },
}

export const WithOrderingAscending = Template.bind({})
WithOrderingAscending.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
        order: 'start_time',
        order_direction: 'ASC',
    },
}

export const WithOrderingDescending = Template.bind({})
WithOrderingDescending.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
        order: 'console_error_count',
        order_direction: 'DESC',
    },
}

export const WithActivityScoreOrdering = Template.bind({})
WithActivityScoreOrdering.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
        order: 'activity_score',
        order_direction: 'DESC',
    },
}

export const ComplexFilters = Template.bind({})
ComplexFilters.args = {
    filters: {
        date_from: '-30d',
        date_to: null,
        duration: [
            {
                type: PropertyFilterType.Recording,
                key: 'duration',
                value: 60,
                operator: PropertyOperator.GreaterThan,
            },
        ],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: PropertyFilterType.Event,
                    key: 'browser',
                    value: ['Chrome', 'Firefox'],
                    operator: PropertyOperator.Exact,
                },
                {
                    type: PropertyFilterType.Person,
                    key: 'email',
                    value: '@company.com',
                    operator: PropertyOperator.IContains,
                },
                {
                    type: PropertyFilterType.Event,
                    key: '$current_url',
                    value: '/checkout',
                    operator: PropertyOperator.IContains,
                },
            ],
        },
        filter_test_accounts: true,
        order: 'console_error_count',
        order_direction: 'DESC',
    },
}

export const NestedFilterGroups = Template.bind({})
NestedFilterGroups.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.Or,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: 'browser',
                            value: 'Chrome',
                            operator: PropertyOperator.Exact,
                        },
                        {
                            type: PropertyFilterType.Event,
                            key: 'browser',
                            value: 'Safari',
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
                {
                    type: PropertyFilterType.Person,
                    key: 'is_identified',
                    value: true,
                    operator: PropertyOperator.Exact,
                },
            ],
        },
    },
}

export const AllFiltersEnabled = Template.bind({})
AllFiltersEnabled.args = {
    filters: {
        date_from: '-14d',
        date_to: '-1d',
        duration: [
            {
                type: PropertyFilterType.Recording,
                key: 'duration',
                value: 30,
                operator: PropertyOperator.GreaterThan,
            },
            {
                type: PropertyFilterType.Recording,
                key: 'duration',
                value: 600,
                operator: PropertyOperator.LessThan,
            },
        ],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: PropertyFilterType.Event,
                    key: 'browser',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                },
                {
                    type: PropertyFilterType.Event,
                    key: '$os',
                    value: ['Mac OS X', 'Windows'],
                    operator: PropertyOperator.Exact,
                },
                {
                    type: FilterLogicalOperator.Or,
                    values: [
                        {
                            type: PropertyFilterType.Person,
                            key: 'email',
                            value: '@gmail.com',
                            operator: PropertyOperator.IContains,
                        },
                        {
                            type: PropertyFilterType.Person,
                            key: 'email',
                            value: '@yahoo.com',
                            operator: PropertyOperator.IContains,
                        },
                    ],
                },
            ],
        },
        filter_test_accounts: true,
        order: 'activity_score',
        order_direction: 'DESC',
    },
}

export const MinimalFilters = Template.bind({})
MinimalFilters.args = {
    filters: {
        date_from: '-3d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
    },
}

export const EmptyFilters = Template.bind({})
EmptyFilters.args = {
    filters: {
        date_from: '-7d',
        date_to: null,
        duration: [],
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [],
        },
    },
}
