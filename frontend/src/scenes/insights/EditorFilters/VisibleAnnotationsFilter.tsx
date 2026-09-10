import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { annotationAppliesToInsight } from 'lib/components/AnnotationsOverlay/annotationsOverlayLogic'
import { LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { annotationScopeToName } from 'scenes/annotations/annotationModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationType } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'

const DATE_FORMAT = 'MMM D, YYYY'

function annotationLabel(annotation: AnnotationType): string {
    const date = annotation.date_marker?.format(DATE_FORMAT)
    const content = annotation.content?.trim()
    if (!content) {
        return date ?? annotationScopeToName[annotation.scope]
    }
    return date ? `${date}: ${content}` : content
}

export function VisibleAnnotationsFilter(): JSX.Element {
    const { insightProps, insight } = useValues(insightLogic)
    const { visibleAnnotationIds } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { annotations, annotationsLoading } = useValues(annotationsModel)

    const options = useMemo((): LemonInputSelectOption[] => {
        return annotations
            .filter((annotation) =>
                annotationAppliesToInsight(annotation, {
                    insightNumericId: insight.id ?? 'new',
                    dashboardId: insightProps.dashboardId,
                    dashboardTiles: insight.dashboard_tiles,
                })
            )
            .sort((a, b) => (b.date_marker?.valueOf() ?? 0) - (a.date_marker?.valueOf() ?? 0))
            .map((annotation) => ({
                key: String(annotation.id),
                label: annotationLabel(annotation),
            }))
    }, [annotations, insight.id, insight.dashboard_tiles, insightProps.dashboardId])

    return (
        <div className="flex flex-col gap-1 w-full max-w-80 px-2 pb-2 pl-4">
            <span>Annotations to show</span>
            <LemonInputSelect
                mode="multiple"
                size="small"
                bulkActions="clear-all"
                allowCustomValues={false}
                virtualized
                loading={annotationsLoading}
                options={options}
                value={(visibleAnnotationIds ?? []).map(String)}
                onChange={(values) => {
                    const ids = values.map((value) => parseInt(value, 10)).filter((id) => !Number.isNaN(id))
                    updateInsightFilter({ visibleAnnotationIds: ids.length ? ids : undefined })
                }}
                placeholder="All annotations"
                emptyStateComponent={<p className="text-secondary m-2">No annotations apply to this insight yet.</p>}
                data-attr="insight-visible-annotations"
            />
        </div>
    )
}
