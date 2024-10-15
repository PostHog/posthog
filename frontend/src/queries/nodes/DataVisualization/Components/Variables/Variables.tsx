import './Variables.scss'

import { IconCopy, IconGear, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useEffect, useRef, useState } from 'react'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { Variable } from '../../types'
import { NewVariableModal } from './NewVariableModal'
import { variablesLogic } from './variablesLogic'

export const VariablesForDashboard = (): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { dashboardVariables } = useValues(dashboardLogic)
    const { overrideVariableValue } = useActions(dashboardLogic)

    if (!featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES] || !dashboardVariables.length) {
        return <></>
    }

    return (
        <>
            <div className="flex gap-4 flex-wrap px-px mt-4">
                {dashboardVariables.map((n) => (
                    <VariableComponent
                        key={n.id}
                        variable={n}
                        showEditingUI={false}
                        onChange={overrideVariableValue}
                        variableOverridesAreSet={false}
                    />
                ))}
            </div>
        </>
    )
}

export const VariablesForInsight = (): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { variablesForInsight, showVariablesBar } = useValues(variablesLogic)
    const { updateVariableValue, removeVariable } = useActions(variablesLogic)
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { variableOverridesAreSet } = useValues(dataNodeLogic)

    if (!featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES] || !variablesForInsight.length || !showVariablesBar) {
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
    onChange: (variableId: string, value: any) => void
    onRemove?: (variableId: string) => void
}

const VariableInput = ({
    variable,
    showEditingUI,
    closePopover,
    onChange,
    onRemove,
}: VariableInputProps): JSX.Element => {
    const [localInputValue, setLocalInputValue] = useState(variable.value ?? variable.default_value ?? '')

    const inputRef = useRef<HTMLInputElement>(null)
    const codeRef = useRef<HTMLElement>(null)

    useEffect(() => {
        inputRef.current?.focus()
    }, [inputRef.current])

    const variableAsHogQL = `{variables.${variable.code_name}}`

    return (
        <div>
            <div className="flex gap-1 p-1">
                <LemonInput
                    inputRef={inputRef}
                    placeholder="Value..."
                    className="flex flex-1"
                    value={localInputValue.toString()}
                    onChange={(value) => setLocalInputValue(value)}
                    onPressEnter={() => {
                        onChange(variable.id, localInputValue)
                        closePopover()
                    }}
                />
                <LemonButton
                    type="primary"
                    onClick={() => {
                        onChange(variable.id, localInputValue)
                        closePopover()
                    }}
                >
                    {showEditingUI ? 'Save' : 'Update'}
                </LemonButton>
            </div>
            {showEditingUI && (
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
                            className="text-xs flex flex-1 items-center"
                        >
                            {variableAsHogQL}
                        </code>
                        <LemonButton
                            icon={<IconCopy />}
                            size="xsmall"
                            onClick={() => void copyToClipboard(variableAsHogQL, 'variable HogQL')}
                            tooltip="Copy HogQL"
                        />
                        {onRemove && (
                            <LemonButton
                                onClick={() => onRemove(variable.id)}
                                icon={<IconTrash />}
                                size="xsmall"
                                tooltip="Remove variable from insight"
                            />
                        )}
                        <LemonButton icon={<IconGear />} size="xsmall" tooltip="Open variable settings" />
                    </div>
                </>
            )}
        </div>
    )
}

interface VariableComponentProps {
    variable: Variable
    showEditingUI: boolean
    onChange: (variableId: string, value: any) => void
    variableOverridesAreSet: boolean
    onRemove?: (variableId: string) => void
}

const VariableComponent = ({
    variable,
    showEditingUI,
    onChange,
    variableOverridesAreSet,
    onRemove,
}: VariableComponentProps): JSX.Element => {
    const [isPopoverOpen, setPopoverOpen] = useState(false)

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
                />
            }
            visible={isPopoverOpen}
            onClickOutside={() => setPopoverOpen(false)}
            className="DataVizVariable_Popover"
        >
            <div>
                <LemonField.Pure
                    label={variable.name}
                    className="gap-0"
                    info={`Use this variable in your HogQL by referencing {variables.${variable.code_name}}`}
                >
                    <LemonButton
                        type="secondary"
                        className="min-w-32 DataVizVariable_Button"
                        onClick={() => setPopoverOpen(!isPopoverOpen)}
                        disabledReason={variableOverridesAreSet && 'Discard dashboard variables to change'}
                    >
                        {variable.value ?? variable.default_value}
                    </LemonButton>
                </LemonField.Pure>
            </div>
        </Popover>
    )
}
