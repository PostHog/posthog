import './Variables.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCopy, IconGear, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    Popover,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { Variable } from '../../types'
import { NewVariableModal } from './NewVariableModal'
import { VariableCalendar } from './VariableCalendar'
import { variableModalLogic } from './variableModalLogic'
import { variablesLogic } from './variablesLogic'

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
}

const VariableInput = ({
    variable,
    showEditingUI,
    closePopover,
    onChange,
    onRemove,
    variableSettingsOnClick,
}: VariableInputProps): JSX.Element => {
    const [localInputValue, setLocalInputValue] = useState<string>(() => {
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

        return String(val ?? '')
    })
    const [isNull, setIsNull] = useState<boolean>(variable.isNull ?? false)

    const inputRef = useRef<HTMLInputElement>(null)
    const codeRef = useRef<HTMLElement>(null)

    useEffect(() => {
        inputRef.current?.focus()
    }, [inputRef.current])

    const variableAsHogQL = `{variables.${variable.code_name}}`

    return (
        <div className="min-w-80">
            <div className={`flex gap-1 p-1 ${isNull ? 'opacity-50 pointer-events-none' : ''}`}>
                {variable.type === 'String' && (
                    <LemonInput
                        inputRef={inputRef}
                        placeholder="Value..."
                        className="flex flex-1"
                        value={localInputValue}
                        onChange={(value) => setLocalInputValue(value)}
                        onPressEnter={() => {
                            onChange(variable.id, localInputValue, isNull)
                            closePopover()
                        }}
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
                        onPressEnter={() => {
                            onChange(variable.id, Number(localInputValue), isNull)
                            closePopover()
                        }}
                    />
                )}
                {variable.type === 'Boolean' && (
                    <LemonSegmentedButton
                        className="grow"
                        value={localInputValue}
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
                    <LemonSelect
                        className="grow"
                        value={localInputValue}
                        onChange={(value) => setLocalInputValue(String(value))}
                        options={variable.values.map((n) => ({ label: n, value: n }))}
                    />
                )}
                {variable.type === 'Date' && (
                    <VariableCalendar
                        value={dayjs(localInputValue)}
                        updateVariable={(date) => {
                            onChange(variable.id, date, isNull)
                            closePopover()
                        }}
                    />
                )}
                {variable.type !== 'Date' && (
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            onChange(
                                variable.id,
                                variable.type === 'Number' ? Number(localInputValue) : localInputValue,
                                isNull
                            )
                            closePopover()
                        }}
                    >
                        {showEditingUI ? 'Save' : 'Update'}
                    </LemonButton>
                )}
            </div>
            {showEditingUI ? (
                <>
                    <LemonDivider className="m1" />

                    <div className="flex p-1">
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
                            className="text-xs flex flex-1 items-center mr-2"
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
    insightsUsingVariable?: string[]
    emptyState?: JSX.Element | string
    size?: 'small' | 'medium'
}

export const VariableComponent = ({
    variable,
    showEditingUI,
    onChange,
    variableOverridesAreSet,
    onRemove,
    variableSettingsOnClick,
    insightsUsingVariable,
    emptyState = '',
    size = 'medium',
}: VariableComponentProps): JSX.Element => {
    const [isPopoverOpen, setPopoverOpen] = useState(false)

    let tooltip = `Use this variable in your HogQL by referencing {variables.${variable.code_name}}`

    if (insightsUsingVariable && insightsUsingVariable.length) {
        tooltip += `. Insights using this variable: ${insightsUsingVariable.join(', ')}`
    }

    // Dont show the popover overlay for list variables not in edit mode
    if (!showEditingUI && variable.type === 'List') {
        return (
            <LemonField.Pure label={variable.name} className="gap-0" info={tooltip}>
                <LemonSelect
                    disabledReason={variableOverridesAreSet && 'Discard dashboard variables to change'}
                    value={variable.value ?? variable.default_value}
                    onChange={(value) => onChange(variable.id, value, variable.isNull ?? false)}
                    options={variable.values.map((n) => ({ label: n, value: n }))}
                />
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
                <LemonField.Pure label={variable.name} className="gap-0" info={tooltip}>
                    <LemonButton
                        type="secondary"
                        className="min-w-32 DataVizVariable_Button"
                        onClick={() => setPopoverOpen(!isPopoverOpen)}
                        disabledReason={variableOverridesAreSet && 'Discard dashboard variables to change'}
                        size={size}
                    >
                        {variable.isNull
                            ? 'Set to null'
                            : (variable.value?.toString() || variable.default_value?.toString() || '') === ''
                              ? emptyState
                              : (variable.value?.toString() ?? variable.default_value?.toString())}
                    </LemonButton>
                </LemonField.Pure>
            </div>
        </Popover>
    )
}
