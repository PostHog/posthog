import './Variables.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCodeInsert, IconCopy, IconGear, IconTrash, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonSegmentedButton,
    LemonSwitch,
    Popover,
    lemonToast,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { DateVariable, ListVariable, Variable } from '../../types'
import { inlineListVariableSelectLogic } from './inlineListVariableSelectLogic'
import { NewVariableModal } from './NewVariableModal'
import { DateField, ListVariableSelect } from './VariableFields'
import { variableModalLogic } from './variableModalLogic'
import { variablesLogic } from './variablesLogic'
import { formatRelativeDateValue, getListVariableSelectedValues, isRelativeDateValue } from './variableUtils'

const getVariableDisplayValue = (variable: Variable): string => {
    const value = variable.value ?? variable.default_value
    if (variable.type === 'List') {
        const selectedValues = getListVariableSelectedValues(variable)
        if (variable.is_multi && selectedValues.length > 1) {
            return `${selectedValues.length} selected`
        }
        return selectedValues[0] ?? ''
    }
    if (variable.type === 'Date' && typeof value === 'string' && isRelativeDateValue(value)) {
        return formatRelativeDateValue(value)
    }
    return String(value ?? '')
}

export const VariablesForDashboard = (): JSX.Element => {
    const { effectiveVariablesAndAssociatedInsights } = useValues(dashboardLogic)
    const { overrideVariableValue } = useActions(dashboardLogic)

    if (!effectiveVariablesAndAssociatedInsights.length) {
        return <></>
    }

    return (
        <>
            {effectiveVariablesAndAssociatedInsights.map((n) => (
                <VariableComponent
                    key={n.variable.id}
                    variable={n.variable}
                    showEditingUI={false}
                    onChange={(variableId, value, isNull) => overrideVariableValue(variableId, value, isNull)}
                    variableOverridesAreSet={false}
                    emptyState={<i className="text-xs">No override set</i>}
                    insightsUsingVariable={n.insightNames}
                    size="small"
                />
            ))}
        </>
    )
}

export const VariablesForInsight = (): JSX.Element => {
    const { variablesForInsight, showVariablesBar } = useValues(variablesLogic)
    const { updateVariableValue, removeVariable } = useActions(variablesLogic)
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { variableOverridesAreSet } = useValues(dataNodeLogic)
    const { openExistingVariableModal } = useActions(variableModalLogic)

    if (!variablesForInsight.length || !showVariablesBar) {
        return <></>
    }

    return (
        <>
            <div className="flex gap-4 flex-wrap px-px">
                {variablesForInsight.map((n) => (
                    <VariableComponent
                        key={n.id}
                        variable={n}
                        showEditingUI={showEditingUI}
                        onChange={updateVariableValue}
                        onRemove={removeVariable}
                        variableOverridesAreSet={variableOverridesAreSet}
                        variableSettingsOnClick={() => openExistingVariableModal(n)}
                    />
                ))}
            </div>
            <NewVariableModal />
        </>
    )
}

interface VariableInputProps {
    variable: Variable
    showEditingUI: boolean
    closePopover: () => void
    onChange: (variableId: string, value: any, isNull: boolean) => void
    onRemove?: (variableId: string) => void
    variableSettingsOnClick?: () => void
    onInsertAtCursor?: (text: string) => void
}

export const VariableInput = ({
    variable,
    showEditingUI,
    closePopover,
    onChange,
    onRemove,
    variableSettingsOnClick,
    onInsertAtCursor,
}: VariableInputProps): JSX.Element => {
    const [localInputValue, setLocalInputValue] = useState<string | string[]>(() => {
        const val = variable.value ?? variable.default_value

        if (variable.type === 'Number' && !val) {
            return '0'
        }

        if (variable.type === 'Boolean') {
            return val === true || val === 'true' ? 'true' : 'false'
        }

        if (variable.type === 'Date' && !val) {
            return dayjs().format('YYYY-MM-DD HH:mm:00')
        }

        if (variable.type === 'List') {
            return getListVariableSelectedValues(variable)
        }

        return String(val ?? '')
    })
    const [isNull, setIsNull] = useState<boolean>(variable.isNull ?? false)

    // A fixed date is committed by the calendar's own Apply button, so a second one would be redundant.
    // The relative-date tab has no such button, and still needs ours.
    const calendarOwnsApply = variable.type === 'Date' && !isRelativeDateValue(String(localInputValue))

    const inputRef = useRef<HTMLInputElement>(null)
    const codeRef = useRef<HTMLElement>(null)

    useEffect(() => {
        inputRef.current?.focus()
    }, [])

    const commit = (value: any): void => {
        onChange(variable.id, value, isNull)
        closePopover()
    }

    const variableAsHogQL = `{variables.${variable.code_name}}`

    return (
        <div className="min-w-80">
            <div className={`flex gap-1 p-1 ${isNull ? 'opacity-50 pointer-events-none' : ''}`}>
                {variable.type === 'String' && (
                    <LemonInput
                        inputRef={inputRef}
                        placeholder="Value..."
                        className="flex flex-1"
                        value={String(localInputValue)}
                        onChange={(value) => setLocalInputValue(value)}
                        onPressEnter={() => commit(localInputValue)}
                    />
                )}
                {variable.type === 'Number' && (
                    <LemonInput
                        type="number"
                        inputRef={inputRef}
                        placeholder="Value..."
                        className="flex flex-1"
                        value={Number(localInputValue)}
                        onChange={(value) => setLocalInputValue(String(value ?? 0))}
                        onPressEnter={() => commit(Number(localInputValue))}
                    />
                )}
                {variable.type === 'Boolean' && (
                    <LemonSegmentedButton
                        className="grow"
                        value={String(localInputValue)}
                        onChange={(value) => setLocalInputValue(value)}
                        options={[
                            {
                                value: 'true',
                                label: 'true',
                            },
                            {
                                value: 'false',
                                label: 'false',
                            },
                        ]}
                    />
                )}
                {variable.type === 'List' && (
                    <ListVariableSelect
                        variable={variable}
                        selectedValues={(Array.isArray(localInputValue) ? localInputValue : [localInputValue]).filter(
                            (value) => value !== ''
                        )}
                        onChange={setLocalInputValue}
                    />
                )}
                {variable.type === 'Date' && (
                    <DateField
                        // The calendar is narrower than the popover, so grow to fill it rather than
                        // leaving dead space down the right-hand side.
                        className="grow"
                        variable={{ ...variable, default_value: String(localInputValue) } as DateVariable}
                        updateVariable={(updatedVariable) => setLocalInputValue(updatedVariable.default_value)}
                        onApply={commit}
                        onSave={() => {}}
                    />
                )}
                {!calendarOwnsApply && (
                    <LemonButton
                        type="primary"
                        // Without this the button stretches to the tallest sibling, which for a date
                        // variable is the relative-date column.
                        className="self-start"
                        onClick={() => commit(variable.type === 'Number' ? Number(localInputValue) : localInputValue)}
                    >
                        {showEditingUI ? 'Save' : 'Update'}
                    </LemonButton>
                )}
            </div>
            {showEditingUI ? (
                <>
                    <LemonDivider className="m1" />

                    {/* Sized off the popover rather than its own content, so a long variable
                        reference wraps instead of stretching the field above it. */}
                    <div className="flex p-1 w-0 min-w-full">
                        <code
                            ref={codeRef}
                            onClick={() => {
                                // Highlight the text by clicking on the element
                                if (window.getSelection && codeRef.current) {
                                    const selection = window.getSelection()
                                    const range = document.createRange()
                                    range.selectNodeContents(codeRef.current)
                                    if (selection) {
                                        selection.removeAllRanges()
                                        selection.addRange(range)
                                    }
                                }
                            }}
                            // The reference is one unbreakable token, so without this a long code
                            // name widens the whole popover instead of wrapping.
                            className="text-xs flex flex-1 items-center mr-2 min-w-0 break-all"
                        >
                            {variableAsHogQL}
                        </code>
                        <LemonSwitch
                            size="xsmall"
                            label="Set to null"
                            checked={isNull}
                            onChange={(value) => {
                                setIsNull(value)
                                onChange(variable.id, null, value)
                            }}
                            bordered
                        />
                        <LemonButton
                            icon={<IconCopy />}
                            size="xsmall"
                            onClick={() => void copyToClipboard(variableAsHogQL, 'variable SQL')}
                            tooltip="Copy SQL"
                        />
                        {onInsertAtCursor && (
                            <LemonButton
                                icon={<IconCodeInsert />}
                                size="xsmall"
                                onClick={() => {
                                    onInsertAtCursor(variableAsHogQL)
                                    closePopover()
                                }}
                                tooltip="Insert into query"
                            />
                        )}
                        {onRemove && (
                            <LemonButton
                                onClick={() => onRemove(variable.id)}
                                icon={<IconTrash />}
                                size="xsmall"
                                tooltip="Remove variable from insight"
                            />
                        )}
                        {variableSettingsOnClick && (
                            <LemonButton
                                onClick={variableSettingsOnClick}
                                icon={<IconGear />}
                                size="xsmall"
                                tooltip="Open variable settings"
                            />
                        )}
                    </div>
                </>
            ) : (
                <>
                    <LemonDivider className="m1" />
                    <div className="flex p-1">
                        <LemonSwitch
                            size="xsmall"
                            label="Set to null"
                            checked={isNull}
                            onChange={(value) => {
                                setIsNull(value)
                                onChange(variable.id, null, value)
                            }}
                            bordered
                        />
                    </div>
                </>
            )}
        </div>
    )
}

interface VariableComponentProps {
    variable: Variable
    showEditingUI: boolean
    onChange: (variableId: string, value: any, isNull: boolean) => void
    variableOverridesAreSet: boolean
    onRemove?: (variableId: string) => void
    variableSettingsOnClick?: () => void
    onInsertAtCursor?: (text: string) => void
    insightsUsingVariable?: string[]
    emptyState?: JSX.Element | string
    size?: 'small' | 'medium'
}

interface BufferedMultiListVariableSelectProps {
    variable: ListVariable
    disabledReason?: string | false
    onChange: (variableId: string, value: string[], isNull: boolean) => void
    size?: 'small' | 'medium'
}

const BufferedMultiListVariableSelect = ({
    variable,
    disabledReason,
    onChange,
    size,
}: BufferedMultiListVariableSelectProps): JSX.Element => {
    const selectedValues = variable.isNull ? [] : getListVariableSelectedValues(variable)
    const logic = inlineListVariableSelectLogic({
        variableId: variable.id,
        selectedValues,
        onChange: (values) => onChange(variable.id, values, values.length === 0),
    })
    const { selectedValues: bufferedValues } = useValues(logic)
    const { commitSelectedValues, setSelectedValues } = useActions(logic)

    return (
        <ListVariableSelect
            variable={variable}
            disabledReason={disabledReason}
            selectedValues={bufferedValues}
            onChange={(value) => setSelectedValues(Array.isArray(value) ? value : value ? [value] : [])}
            onBlur={commitSelectedValues}
            size={size}
        />
    )
}

export const VariableComponent = ({
    variable,
    showEditingUI,
    onChange,
    variableOverridesAreSet,
    onRemove,
    variableSettingsOnClick,
    onInsertAtCursor,
    insightsUsingVariable,
    emptyState = '',
    size = 'medium',
}: VariableComponentProps): JSX.Element => {
    const [isPopoverOpen, setPopoverOpen] = useState(false)

    const variableAsHogQL = `{variables.${variable.code_name}}`

    const tooltip =
        insightsUsingVariable && insightsUsingVariable.length > 0 ? (
            <div className="flex flex-col gap-1">
                <span>Insights using this variable: {insightsUsingVariable.join(', ')}</span>
            </div>
        ) : undefined

    // Don't show the popover overlay for list variables not in edit mode
    if (!showEditingUI && variable.type === 'List') {
        const disabledReason = variableOverridesAreSet && 'Discard dashboard variables to change'
        return (
            <LemonField.Pure label={variable.name} className="gap-0" info={tooltip}>
                {variable.is_multi ? (
                    <BufferedMultiListVariableSelect
                        variable={variable}
                        disabledReason={disabledReason}
                        onChange={onChange}
                        size={size}
                    />
                ) : (
                    <ListVariableSelect
                        variable={variable}
                        disabledReason={disabledReason}
                        selectedValues={variable.isNull ? [] : getListVariableSelectedValues(variable)}
                        onChange={(value) => onChange(variable.id, value, value === '')}
                        size={size}
                    />
                )}
            </LemonField.Pure>
        )
    }

    return (
        <Popover
            key={variable.id}
            overlay={
                <VariableInput
                    variable={variable}
                    showEditingUI={showEditingUI}
                    onChange={onChange}
                    closePopover={() => setPopoverOpen(false)}
                    onRemove={onRemove}
                    onInsertAtCursor={onInsertAtCursor}
                    variableSettingsOnClick={() => {
                        if (variableSettingsOnClick) {
                            setPopoverOpen(false)
                            variableSettingsOnClick()
                        }
                    }}
                />
            }
            fallbackPlacements={['top-end', 'top-start', 'bottom-end', 'bottom-start']}
            visible={isPopoverOpen}
            onClickOutside={() => setPopoverOpen(false)}
            className="DataVizVariable_Popover"
        >
            <div>
                <LemonField.Pure label={variable.name} className="gap-0">
                    <div className="flex gap-x-2">
                        <LemonButton
                            type="secondary"
                            className="min-w-32 DataVizVariable_Button"
                            onClick={() => setPopoverOpen(!isPopoverOpen)}
                            disabledReason={variableOverridesAreSet && 'Discard dashboard variables to change'}
                            size={size}
                        >
                            {variable.isNull ? 'Set to null' : getVariableDisplayValue(variable) || emptyState}
                        </LemonButton>
                        {showEditingUI && (
                            <LemonButton
                                icon={<IconCopy />}
                                onClick={() => {
                                    navigator.clipboard.writeText(variableAsHogQL)
                                    lemonToast.success(
                                        <span>
                                            <code className="text-sm">{variableAsHogQL}</code> copied to clipboard. Use
                                            it anywhere in HogQL.
                                        </span>
                                    )
                                }}
                                type="secondary"
                                tooltip="Copy variable code name"
                                noPadding
                                size="small"
                            />
                        )}
                        {showEditingUI && onInsertAtCursor && (
                            <LemonButton
                                icon={<IconCodeInsert />}
                                onClick={() => {
                                    onInsertAtCursor(variableAsHogQL)
                                    lemonToast.success(
                                        <span>
                                            <code className="text-sm">{variableAsHogQL}</code> inserted into query.
                                        </span>
                                    )
                                }}
                                type="secondary"
                                tooltip="Insert into query at cursor"
                                noPadding
                                size="small"
                            />
                        )}
                        {onRemove && showEditingUI && (
                            <LemonButton
                                icon={<IconX className="h-4 w-4" />}
                                onClick={() => {
                                    onRemove(variable.id)
                                }}
                                type="secondary"
                                status="danger"
                                tooltip="Remove from this query"
                                noPadding
                                size="small"
                            />
                        )}
                    </div>
                </LemonField.Pure>
            </div>
        </Popover>
    )
}
