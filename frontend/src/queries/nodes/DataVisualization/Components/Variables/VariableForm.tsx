import { IconCopy, IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { Variable, VariableType } from '../../types'
import {
    BooleanField,
    DateField,
    DirectFieldProps,
    ListVariableFields,
    NumberField,
    StringField,
    VARIABLE_TYPE_OPTIONS,
    formatVariableReference,
    getCodeName,
} from './VariableFields'

function renderField<T extends Variable>(
    Field: React.ComponentType<DirectFieldProps<T>>,
    variable: Variable,
    updateVariable: (variable: Variable) => void,
    onSave: () => void,
    label: string
): JSX.Element {
    return (
        <LemonField.Pure label={label} className="gap-1">
            <Field variable={variable as T} updateVariable={updateVariable as (variable: T) => void} onSave={onSave} />
        </LemonField.Pure>
    )
}

export const VariableSpecificFields = ({
    variable,
    updateVariable,
    onSave,
    defaultValuesQueryConnectionId,
}: {
    variable: Variable
    updateVariable: (variable: Variable) => void
    onSave: () => void
    defaultValuesQueryConnectionId?: string | null
}): JSX.Element => {
    switch (variable.type) {
        case 'String':
            return renderField(StringField, variable, updateVariable, onSave, 'Default value')
        case 'Number':
            return renderField(NumberField, variable, updateVariable, onSave, 'Default value')
        case 'Boolean':
            return renderField(BooleanField, variable, updateVariable, onSave, 'Default value')
        case 'List':
            return (
                <ListVariableFields
                    variable={variable}
                    updateVariable={updateVariable}
                    onSave={onSave}
                    defaultValuesQueryConnectionId={defaultValuesQueryConnectionId}
                />
            )
        case 'Date':
            return renderField(DateField, variable, updateVariable, onSave, 'Default value')
    }
}

export interface VariableFormProps {
    variable: Variable
    updateVariable: (variable: Variable) => void
    onSave: () => void
    modalType: 'new' | 'existing'
    onTypeChange: (variableType: VariableType) => void
    defaultValuesQueryConnectionId?: string | null
}

export const VariableForm = ({
    variable,
    updateVariable,
    onSave,
    onTypeChange,
    defaultValuesQueryConnectionId,
}: VariableFormProps): JSX.Element => {
    const codeNameFallback = getCodeName(variable.name)
    const referenceCodeName = variable.code_name || codeNameFallback
    const nameLabel = (
        <span className="inline-flex items-center gap-1">
            Name
            <Tooltip title="Variable name must be alphanumeric and can only contain spaces and underscores">
                <IconInfo className="text-xl text-secondary shrink-0" />
            </Tooltip>
        </span>
    )
    return (
        <div className="gap-4 flex flex-col">
            <LemonField.Pure label={nameLabel} className="gap-1">
                <LemonInput
                    placeholder="Name"
                    value={variable.name}
                    onChange={(value) => {
                        const filteredValue = value.replace(/[^a-zA-Z0-9\s_]/g, '')
                        updateVariable({ ...variable, name: filteredValue })
                    }}
                />
                {referenceCodeName && (
                    <span className="text-xs">
                        Use this variable by referencing <code>{formatVariableReference(referenceCodeName)}</code>
                        <LemonButton
                            className="inline-block align-middle"
                            icon={<IconCopy />}
                            type="tertiary"
                            size="xsmall"
                            onClick={() => {
                                copyToClipboard(formatVariableReference(referenceCodeName), 'code')
                            }}
                            tooltip="Copy to clipboard"
                        />
                    </span>
                )}
            </LemonField.Pure>
            <LemonField.Pure label="Type" className="gap-1">
                <LemonSelect
                    value={variable.type}
                    onChange={(value) => {
                        onTypeChange(value as VariableType)
                    }}
                    options={VARIABLE_TYPE_OPTIONS}
                />
            </LemonField.Pure>
            <VariableSpecificFields
                variable={variable}
                updateVariable={updateVariable}
                onSave={onSave}
                defaultValuesQueryConnectionId={defaultValuesQueryConnectionId}
            />
        </div>
    )
}
