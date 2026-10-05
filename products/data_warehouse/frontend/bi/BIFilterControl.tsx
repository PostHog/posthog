import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { biEditorLogic } from 'scenes/data-warehouse/editor/bi/biEditorLogic'
import {
    getBIFieldPillLabel,
    getBIFilterSummary,
    getBIFilterValidationError,
    getBIShelfEditorKey,
} from 'scenes/data-warehouse/editor/bi/biEditorTypes'
import { BIFilterEditor } from 'scenes/data-warehouse/editor/bi/components/BIFilterEditor'

export function BIFilterControl({ index }: { index: number }): JSX.Element | null {
    const { config, activeExpressionEditorId } = useValues(biEditorLogic)
    const { updateFilter, setActiveExpressionEditorId } = useActions(biEditorLogic)
    const filter = config.filters[index]
    if (!filter) {
        return null
    }
    const label = getBIFieldPillLabel(filter.field)
    const editorKey = `${getBIShelfEditorKey('filters', filter.field.id)}:quick`
    const validationError = getBIFilterValidationError(filter)
    const summary = getBIFilterSummary(filter)
    const close = (): void => {
        if (activeExpressionEditorId === editorKey) {
            setActiveExpressionEditorId(null)
        }
    }

    return (
        <div className="flex min-w-0 flex-col gap-0.5" data-attr="bi-filter-control">
            <LemonCheckbox
                checked={filter.enabled !== false}
                onChange={(enabled) => updateFilter(index, { enabled })}
                label={
                    <span
                        className={cn(
                            'block truncate text-xs font-normal',
                            filter.enabled === false && 'text-tertiary'
                        )}
                    >
                        {label}
                    </span>
                }
                aria-label={`Apply ${label} filter`}
                size="xsmall"
                className="min-w-0 [&_.LemonCheckbox__label]:min-w-0"
                labelClassName="min-w-0 flex-1 !min-h-4 !leading-4"
                data-attr="bi-filter-enabled"
            />
            <LemonDropdown
                visible={activeExpressionEditorId === editorKey}
                onVisibilityChange={(visible) => (visible ? setActiveExpressionEditorId(editorKey) : close())}
                closeOnClickInside={false}
                placement="left-start"
                overlay={<BIFilterEditor index={index} onDone={close} />}
            >
                <LemonButton
                    type="secondary"
                    size="xxsmall"
                    fullWidth
                    sideIcon={<IconChevronDown />}
                    status={validationError ? 'danger' : 'default'}
                    className={cn('font-normal', filter.enabled === false && 'opacity-50')}
                    tooltip={
                        validationError ||
                        (filter.operator === 'between'
                            ? `${filter.value || 'Any'} to ${filter.valueTo || 'any'}`
                            : summary)
                    }
                    aria-label={`Edit ${label} filter values`}
                    data-attr="bi-filter-edit-values"
                >
                    <span className="truncate font-normal">{validationError ? 'Invalid number' : summary}</span>
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
