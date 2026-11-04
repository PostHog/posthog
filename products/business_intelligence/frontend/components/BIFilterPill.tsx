import { useActions, useValues } from 'kea'

import { LemonDropdown } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { getBIFilterValidationError, getBIShelfEditorKey } from 'products/business_intelligence/frontend/biEditorTypes'
import { BIFilterEditor } from 'products/business_intelligence/frontend/components/BIFilterEditor'
import { BIPill } from 'products/business_intelligence/frontend/components/BIPill'

import { getBIFilterLabel, describeBIFilter } from '../biFilterSummary'

export function BIFilterPill({ index }: { index: number }): JSX.Element | null {
    const { config, activeExpressionEditorId } = useValues(biEditorLogic)
    const { setActiveExpressionEditorId, removeFieldFromShelf } = useActions(biEditorLogic)
    const filter = config.filters[index]
    if (!filter) {
        return null
    }

    const editorKey = getBIShelfEditorKey('filters', filter.field.id)
    const visible = activeExpressionEditorId === editorKey
    const close = (removed = false): void => {
        if (activeExpressionEditorId === editorKey) {
            setActiveExpressionEditorId(null)
            if (!removed && !filter.field.expression.trim() && !filter.customExpression?.trim()) {
                removeFieldFromShelf('filters', index)
            }
        }
    }
    const label = getBIFilterLabel(filter)
    const description = describeBIFilter(filter, config)

    return (
        <LemonDropdown
            visible={visible}
            onVisibilityChange={(nextVisible) => (nextVisible ? setActiveExpressionEditorId(editorKey) : close())}
            closeOnClickInside={false}
            placement="bottom-start"
            overlay={<BIFilterEditor index={index} onDone={close} />}
        >
            <BIPill
                kind="filter"
                label={label}
                detail={getBIFilterValidationError(filter) ? 'Invalid' : filter.enabled === false ? 'Off' : description}
                title={`${label}: ${description}`}
                shelf="filters"
                index={index}
                incomplete={!filter.field.expression.trim() && !filter.customExpression?.trim()}
                className={cn(
                    'h-5 max-w-64 justify-between px-1.5 font-normal',
                    filter.enabled === false && 'opacity-50'
                )}
                aria-label={`${label} filter`}
                data-attr="bi-editor-filters-pill"
            />
        </LemonDropdown>
    )
}
