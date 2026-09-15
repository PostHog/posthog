import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { AnnotationScope } from '~/types'

import { annotationScopeToName } from 'products/annotations/frontend/logics/annotationModalLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

type AnnotationsSelection = AnnotationScope | 'all' | 'none'

const OPTIONS: LemonSelectOptions<AnnotationsSelection> = [
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

    return (
        <LemonSelect
            className="mb-2.5 mx-2"
            size="small"
            fullWidth
            value={showAnnotations === false ? 'none' : (annotationsScope ?? 'all')}
            options={OPTIONS}
            onChange={(selection) =>
                updateInsightFilter({
                    showAnnotations: selection === 'none' ? false : undefined,
                    annotationsScope: selection === 'all' || selection === 'none' ? undefined : selection,
                })
            }
            data-attr="insight-annotations-picker"
        />
    )
}
