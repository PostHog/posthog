import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { AnnotationScope } from '~/types'

import { annotationScopeToName } from 'products/annotations/frontend/logics/annotationModalLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'

const SCOPE_OPTIONS: LemonSelectOptions<AnnotationScope | null> = [
    { value: null, label: 'all' },
    ...Object.values(AnnotationScope).map((scope) => ({
        value: scope,
        label: scope === AnnotationScope.Organization ? 'org' : annotationScopeToName[scope].toLowerCase(),
        labelInMenu: annotationScopeToName[scope].toLowerCase(),
    })),
]

export function AnnotationsOptionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showAnnotations, annotationsScope } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const enabled = showAnnotations !== false

    return (
        <div className="flex items-center gap-1 p-1 px-2">
            <LemonCheckbox
                onChange={(value) => updateInsightFilter({ showAnnotations: value })}
                checked={enabled}
                label={<span className="font-normal">Show</span>}
                size="small"
            />
            <LemonSelect
                size="xsmall"
                value={annotationsScope ?? null}
                options={SCOPE_OPTIONS}
                truncateText={{ maxWidthClass: 'max-w-12' }}
                disabledReason={enabled ? undefined : 'Turn on annotations to filter them by scope'}
                onChange={(scope) => updateInsightFilter({ annotationsScope: scope ?? undefined })}
                data-attr="insight-annotations-scope-select"
            />
            <span>annotations</span>
        </div>
    )
}
