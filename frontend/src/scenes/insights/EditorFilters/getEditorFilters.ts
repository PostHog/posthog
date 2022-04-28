import { FilterType, InsightEditorFilter, InsightEditorFilterGroups, InsightType } from '~/types'
import { EditorFilterInsightType } from 'scenes/insights/EditorFilters/EditorFilterInsightType'
import { EditorFilterTrendsSteps } from 'scenes/insights/EditorFilters/EditorFilterTrendsSteps'
import { EditorFilterTrendsGlobalFilters } from 'scenes/insights/EditorFilters/EditorFilterTrendsGlobalFilters'

const isTrends = {
    [InsightType.TRENDS]: true,
    [InsightType.STICKINESS]: true,
    [InsightType.LIFECYCLE]: true,
    [InsightType.FUNNELS]: true,
}

export function getEditorFilters(filters: Partial<FilterType>): InsightEditorFilterGroups {
    return {
        General: [
            {
                key: 'insight',
                label: 'Type',
                valueSelector: (i) => i.filters?.insight,
                component: EditorFilterInsightType,
            },
        ],
        Steps: removeFalsy([
            isTrends[filters.insight ?? InsightType.TRENDS] && {
                key: 'steps',
                component: EditorFilterTrendsSteps,
            },
        ]),
        Filters: [
            {
                key: 'properties',
                label: 'Something goes here',
                component: EditorFilterTrendsGlobalFilters,
            },
        ],
    }
}

function removeFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e) => !!e) as InsightEditorFilter[]
}
