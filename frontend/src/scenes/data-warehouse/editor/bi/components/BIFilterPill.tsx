import { useActions, useValues } from 'kea'

import { LemonDropdown } from '@posthog/lemon-ui'

import { biEditorLogic } from '../biEditorLogic'
import { FILTER_OPERATOR_OPTIONS } from '../biEditorOptions'
import { BIFilter, getBIFieldPillLabel, getBIShelfEditorKey } from '../biEditorTypes'
import { BIFilterEditor } from './BIFilterEditor'
import { BIPill } from './BIPill'

function filterSummary(filter: BIFilter): string | undefined {
    const operatorLabel = FILTER_OPERATOR_OPTIONS.find((option) => option.value === filter.operator)?.label
    if (filter.operator === 'custom') {
        return filter.customExpression?.trim() || undefined
    }
    if (['last_7_days', 'is_set', 'is_not_set'].includes(filter.operator)) {
        return operatorLabel?.toLowerCase()
    }
    return filter.value.trim() ? `${operatorLabel?.toLowerCase()} ${filter.value}` : undefined
}

export function BIFilterPill({ index }: { index: number }): JSX.Element | null {
    const { config, activeExpressionEditorId } = useValues(biEditorLogic)
    const { setActiveExpressionEditorId } = useActions(biEditorLogic)
    const filter = config.filters[index]
    if (!filter) {
        return null
    }

    const editorKey = getBIShelfEditorKey('filters', filter.field.id)
    const visible = activeExpressionEditorId === editorKey
    const close = (): void => {
        if (activeExpressionEditorId === editorKey) {
            setActiveExpressionEditorId(null)
        }
    }
    const label = getBIFieldPillLabel(filter.field)
    const summary = filterSummary(filter)

    return (
        <LemonDropdown
            visible={visible}
            onVisibilityChange={(nextVisible) => (nextVisible ? setActiveExpressionEditorId(editorKey) : close())}
            closeOnClickInside={false}
            placement="right-start"
            overlay={<BIFilterEditor index={index} onDone={close} />}
        >
            <BIPill
                kind="filter"
                label={label}
                detail={summary}
                shelf="filters"
                index={index}
                incomplete={!filter.field.expression.trim() && !filter.customExpression?.trim()}
                className="w-full justify-between"
                aria-label={`${label} filter`}
                data-attr="bi-editor-filters-pill"
            />
        </LemonDropdown>
    )
}
