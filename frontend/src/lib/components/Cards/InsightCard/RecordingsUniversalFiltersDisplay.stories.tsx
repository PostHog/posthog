import type { Meta, StoryObj } from '@storybook/react'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

import { RecordingsUniversalFiltersDisplay as RecordingsUniversalFiltersDisplayComponent } from './RecordingsUniversalFiltersDisplay'

type Story = StoryObj<{ filters: RecordingUniversalFilters }>
const meta: Meta<{ filters: RecordingUniversalFilters }> = {
    title: 'Components/Cards/Recordings Universal Filters Display',
    component: RecordingsUniversalFiltersDisplayComponent as any,
    render: ({ filters }) => {
        return (
            <div className="bg-surface-primary w-[24rem] p-4 rounded">
                <RecordingsUniversalFiltersDisplayComponent filters={filters} />
            </div>
        )
    },
}
export default meta

export const BasicDateRange: Story = {
    args: {
        filters: {
            date_from: '-7d',
            date_to: null,
            duration: [],
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [],
            },
        },
    },
}

export const CustomDateRange: Story = {
    args: {
        filters: {
            date_from: '2024-01-01',
            date_to: '2024-01-31',
            duration: [],
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [],
            },
        },
    },
}

export const WithDurationFilter: Story = {
    args: {
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
    },
}

export const WithMultipleDurationFilters: Story = {
    args: {
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
    },
}

export const WithPropertyFilters: Story = {
    args: {
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
    },
}

export const WithOrFilters: Story = {
    args: {
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
    },
}

export const WithCohortFilter: Story = {
    args: {
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
    },
}

export const WithTestAccountsExcluded: Story = {
    args: {
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
    },
}

export const WithOrderingAscending: Story = {
    args: {
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
    },
}

export const WithOrderingDescending: Story = {
    args: {
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
    },
}

export const WithActivityScoreOrdering: Story = {
    args: {
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
    },
}

export const ComplexFilters: Story = {
    args: {
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
    },
}

export const NestedFilterGroups: Story = {
    args: {
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
    },
}

export const AllFiltersEnabled: Story = {
    args: {
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
    },
}

export const MinimalFilters: Story = {
    args: {
        filters: {
            date_from: '-3d',
            date_to: null,
            duration: [],
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [],
            },
        },
    },
}

export const EmptyFilters: Story = {
    args: {
        filters: {
            date_from: '-7d',
            date_to: null,
            duration: [],
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [],
            },
        },
    },
}
