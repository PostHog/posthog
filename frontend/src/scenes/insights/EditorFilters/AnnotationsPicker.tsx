import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'

import { QuillDisplayOptionSelect } from '~/queries/nodes/InsightViz/QuillDisplayOptionSelect'
import { AnnotationScope } from '~/types'

import { annotationScopeToName } from 'products/annotations/frontend/logics/annotationModalLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

type AnnotationsSelection = AnnotationScope | 'all' | 'none'

const OPTIONS: { value: AnnotationsSelection; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'none', label: 'None' },
    ...Object.values(AnnotationScope).map((scope) => ({
        value: scope,
        label: annotationScopeToName[scope],
    })),
]

export function AnnotationsPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showAnnotations, annotationsScope } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const value = showAnnotations === false ? 'none' : (annotationsScope ?? 'all')
    const onSelectionChange = (selection: AnnotationsSelection): void =>
        updateInsightFilter({
            showAnnotations: selection === 'none' ? false : undefined,
            annotationsScope: selection === 'all' || selection === 'none' ? undefined : selection,
        })

    if (todayRailNav) {
        return (
            <QuillDisplayOptionSelect
                value={value}
                options={OPTIONS}
                onChange={onSelectionChange}
                fullWidth
                data-attr="insight-annotations-picker"
            />
        )
    }

    return (
        <div className="mb-2.5 mx-2">
            <LemonSelect
                size="small"
                fullWidth
                value={value}
                options={OPTIONS}
                onChange={onSelectionChange}
                data-attr="insight-annotations-picker"
            />
        </div>
    )
}
