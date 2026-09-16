import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { annotationsFilterLogic } from './annotationsFilterLogic'
import { AnnotationsFilterPopover } from './AnnotationsFilterPopover'

export function AnnotationsOptionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showAnnotations } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { isFilterActive } = useValues(annotationsFilterLogic(insightProps))

    const enabled = showAnnotations !== false

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <LemonCheckbox
                onChange={(value) => updateInsightFilter({ showAnnotations: value })}
                checked={enabled}
                label={<span className="font-normal">Show annotations</span>}
                size="small"
            />
            <LemonDropdown closeOnClickInside={false} placement="bottom-end" overlay={<AnnotationsFilterPopover />}>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    active={isFilterActive}
                    disabledReason={enabled ? undefined : 'Turn on annotations to filter them'}
                    data-attr="insight-annotations-filter-button"
                >
                    Filters
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
