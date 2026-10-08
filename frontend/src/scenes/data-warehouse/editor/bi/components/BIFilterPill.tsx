import { useActions, useValues } from 'kea'

import { LemonDropdown } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { biEditorLogic } from '../biEditorLogic'
import {
    getBIFieldPillLabel,
    getBIFilterSummary,
    getBIFilterValidationError,
    getBIShelfEditorKey,
} from '../biEditorTypes'
import { BIFilterEditor } from './BIFilterEditor'
import { BIPill } from './BIPill'

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
                detail={getBIFilterValidationError(filter) ? 'Invalid' : filter.enabled === false ? 'Off' : undefined}
                title={`${label}: ${getBIFilterSummary(filter)}`}
                shelf="filters"
                index={index}
                incomplete={!filter.field.expression.trim() && !filter.customExpression?.trim()}
                className={cn(
                    'h-5 w-full justify-between px-1.5 font-normal',
                    filter.enabled === false && 'opacity-50'
                )}
                aria-label={`${label} filter`}
                data-attr="bi-editor-filters-pill"
            />
        </LemonDropdown>
    )
}
