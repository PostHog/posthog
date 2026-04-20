import type { Meta, StoryObj } from '@storybook/react'
import { userEvent, waitFor } from '@storybook/testing-library'
import { BindLogic, useMountedLogic, useValues } from 'kea'
import { useRef, useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS, SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { alphabet, uuid } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isFilterWithDisplay, isLifecycleFilter } from 'scenes/insights/sharedUtils'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { FilterType, InsightLogicProps, InsightType } from '~/types'

import { ActionFilter, ActionFilterProps } from './ActionFilter'
import { MathAvailability } from './ActionFilterRow/ActionFilterRow'

type Story = StoryObj<ActionFilterProps>
const meta: Meta<ActionFilterProps> = {
    title: 'Filters/Action Filter',
    decorators: [taxonomicFilterMocksDecorator],
}
export default meta

let uniqueNode = 0

const renderActionFilter = ({ ...props }: Partial<ActionFilterProps>): JSX.Element => {
    useMountedLogic(cohortsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const id = useRef(uuid())

    const [filters, setFilters] = useState<FilterType>({
        insight: InsightType.TRENDS,
        events: [
            {
                id: '$pageview',
                name: '$pageview',
                order: 0,
                type: 'events',
                properties: [
                    {
                        key: '$browser',
                        value: ['Chrome'],
                        operator: 'exact',
                        type: 'person',
                    },
                ],
            },
        ],
    })

    const [dashboardItemId] = useState(() => `ActionFilterStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')
    const cachedInsight = { ...insight, short_id: dashboardItemId, filters }
    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                typeKey={`trends_${id.current}`}
                buttonCopy="Add graph series"
                showSeriesIndicator
                entitiesLimit={
                    isLifecycleFilter(filters) ||
                    (isFilterWithDisplay(filters) &&
                        filters.display &&
                        SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display))
                        ? 1
                        : alphabet.length
                }
                mathAvailability={
                    filters.insight === InsightType.LIFECYCLE
                        ? MathAvailability.None
                        : filters.insight === InsightType.STICKINESS
                          ? MathAvailability.ActorsOnly
                          : MathAvailability.All
                }
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]}
                {...props}
            />
        </BindLogic>
    )
}

export const Standard: Story = {
    render: renderActionFilter,
    args: {},
}

export const Bordered: Story = {
    render: renderActionFilter,
    args: {
        bordered: true,
    },
}

export const PropertyFiltersWithPopover: Story = {
    render: renderActionFilter,
    args: {
        propertyFiltersPopover: true,
    },
}

export const Sortable: Story = {
    render: renderActionFilter,
    args: {
        sortable: true,
    },
}

export const FunnelLike: Story = {
    render: renderActionFilter,
    args: {
        sortable: true,
        bordered: true,
        seriesIndicatorType: 'numeric',
    },
}

export const SingleFilter: Story = {
    render: renderActionFilter,
    args: {
        entitiesLimit: 1,
    },
}

const renderAutocaptureFilter = ({ ...props }: Partial<ActionFilterProps>): JSX.Element => {
    useMountedLogic(cohortsModel)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const id = useRef(uuid())

    const [filters, setFilters] = useState<FilterType>({
        insight: InsightType.TRENDS,
        events: [
            {
                id: '$autocapture',
                name: '$autocapture',
                order: 0,
                type: 'events',
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: 'exact',
                        type: 'event',
                    },
                    {
                        key: 'selector',
                        value: '.btn-primary',
                        operator: 'exact',
                        type: 'element',
                    },
                ],
            },
        ],
    })

    const [dashboardItemId] = useState(() => `ActionFilterStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const insight = require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')
    const cachedInsight = { ...insight, short_id: dashboardItemId, filters }
    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                typeKey={`trends_${id.current}`}
                buttonCopy="Add graph series"
                showSeriesIndicator
                mathAvailability={MathAvailability.All}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]}
                {...props}
            />
        </BindLogic>
    )
}

export const AutocaptureWithSaveAsAction: Story = {
    render: renderAutocaptureFilter,
    args: {},
    parameters: {
        featureFlags: [FEATURE_FLAGS.AUTOCAPTURE_SAVE_AS_ACTION],
        testOptions: { waitForSelector: '[data-attr="autocapture-save-as-action"]' },
    },
    play: async ({ canvasElement }) => {
        const filterToggle = await waitFor(
            () => {
                const button = canvasElement.querySelector<HTMLElement>('[data-attr="show-prop-filter-0"]')
                if (!button) {
                    throw new Error('Filters button not yet rendered')
                }
                return button
            },
            { timeout: 2000 }
        )
        await userEvent.click(filterToggle)
    },
}
