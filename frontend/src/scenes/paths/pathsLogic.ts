import { kea } from 'kea'
import { router } from 'kea-router'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

import type { pathsLogicType } from './pathsLogicType'
import { InsightLogicProps, FilterType, PathType, InsightType, PathsFilterType, AnyPropertyFilter } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { isPathsFilter } from 'scenes/insights/sharedUtils'
import { urls } from 'scenes/urls'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { buildPeopleUrl, pathsTitle } from 'scenes/trends/persons-modal/persons-modal-utils'
import { PathNodeData } from './pathUtils'

export const DEFAULT_STEP_LIMIT = 5

export const pathOptionsToLabels = {
    [PathType.PageView]: 'Page views (Web)',
    [PathType.Screen]: 'Screen views (Mobile)',
    [PathType.CustomEvent]: 'Custom events',
}

export const pathOptionsToProperty = {
    [PathType.PageView]: '$current_url',
    [PathType.Screen]: '$screen_name',
    [PathType.CustomEvent]: 'custom_event',
}

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'
export interface PathResult {
    paths: PathNode[]
    filter: Partial<FilterType>
    error?: boolean
}

export interface PathNode {
    target: string
    source: string
    value: number
}

export const pathsLogic = kea<pathsLogicType>({
    path: (key) => ['scenes', 'paths', 'pathsLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_PATH_LOGIC_KEY),

    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters as inflightFilters', 'insight', 'insightLoading'],
            trendsLogic(props),
            ['aggregationTargetLabel'],
        ],
        actions: [insightLogic(props), ['loadResultsSuccess']],
    }),

    actions: {
        setProperties: (properties: AnyPropertyFilter[]) => ({ properties }),
        setFilter: (filter: Partial<PathsFilterType>) => ({ filter }),
        openPersonsModal: (props: { path_start_key?: string; path_end_key?: string; path_dropoff_key?: string }) =>
            props,
        viewPathToFunnel: (pathItemCard: PathNodeData) => ({ pathItemCard }),
    },
    listeners: ({ values, props }) => ({
        setProperties: ({ properties }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filter, properties }))
        },
        setFilter: ({ filter }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filter, ...filter }))
        },
        openPersonsModal: ({ path_start_key, path_end_key, path_dropoff_key }) => {
            const filters: Partial<PathsFilterType> = {
                ...values.filter,
                path_start_key,
                path_end_key,
                path_dropoff_key,
            }
            const personsUrl = buildPeopleUrl({
                date_from: '',
                date_to: '',
                filters,
            })
            if (personsUrl) {
                openPersonsModal({
                    url: personsUrl,
                    title: pathsTitle({
                        label: path_dropoff_key || path_start_key || path_end_key || 'Pageview',
                        isDropOff: Boolean(path_dropoff_key),
                    }),
                })
            }
        },
        viewPathToFunnel: ({ pathItemCard }) => {
            const events = []
            let currentItemCard = pathItemCard
            while (currentItemCard.targetLinks.length > 0) {
                const name = currentItemCard.name.includes('http')
                    ? '$pageview'
                    : currentItemCard.name.replace(/(^[0-9]+_)/, '')
                events.push({
                    id: name,
                    name: name,
                    type: 'events',
                    order: currentItemCard.depth - 1,
                    ...(currentItemCard.name.includes('http') && {
                        properties: [
                            {
                                key: '$current_url',
                                operator: 'exact',
                                type: 'event',
                                value: currentItemCard.name.replace(/(^[0-9]+_)/, ''),
                            },
                        ],
                    }),
                })
                currentItemCard = currentItemCard.targetLinks[0].source
            }
            router.actions.push(
                urls.insightNew({
                    insight: InsightType.FUNNELS,
                    events,
                    date_from: values.filter.date_from,
                })
            )
        },
    }),
})
