import './Variables.scss'

import { IconCopy, IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useEffect, useRef, useState } from 'react'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { Variable } from '../../types'
import { NewVariableModal } from './NewVariableModal'
import { variablesLogic } from './variablesLogic'

export const Variables = (): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { variablesForInsight } = useValues(variablesLogic)

    if (!featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES] || !variablesForInsight.length) {
        return <></>
    }

    return (
        <>
            <div className="flex gap-4 flex-wrap px-px">
                {variablesForInsight.map((n) => (
                    <VariableComponent key={n.id} variable={n} />
                ))}
            </div>
            <NewVariableModal />
        </>
    )
}

const VariableInput = ({ variable, closePopover }: { variable: Variable; closePopover: () => void }): JSX.Element => {
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { updateVariableValue } = useActions(variablesLogic)

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
                        updateVariableValue(variable.id, localInputValue)
                        closePopover()
                    }}
                />
                <LemonButton
                    type="primary"
                    onClick={() => {
                        updateVariableValue(variable.id, localInputValue)
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
                        <LemonButton icon={<IconGear />} size="xsmall" tooltip="Open variable settings" />
                    </div>
                </>
            )}
        </div>
    )
}

const VariableComponent = ({ variable }: { variable: Variable }): JSX.Element => {
    const [isPopoverOpen, setPopoverOpen] = useState(false)

    return (
        <Popover
            key={variable.id}
            overlay={<VariableInput variable={variable} closePopover={() => setPopoverOpen(false)} />}
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
                    >
                        {variable.value ?? variable.default_value}
                    </LemonButton>
                </LemonField.Pure>
            </div>
        </Popover>
    )
}
