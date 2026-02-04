import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { Variable, VariableType } from '../../types'
import {
    BooleanField,
    DateField,
    DirectFieldProps,
    ListDefaultField,
    ListValuesField,
    NumberField,
    StringField,
    VARIABLE_TYPE_OPTIONS,
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

const renderVariableSpecificFields = (
    variable: Variable,
    updateVariable: (variable: Variable) => void,
    onSave: () => void
): JSX.Element => {
    switch (variable.type) {
        case 'String':
            return renderField(StringField, variable, updateVariable, onSave, 'Default value')
        case 'Number':
            return renderField(NumberField, variable, updateVariable, onSave, 'Default value')
        case 'Boolean':
            return renderField(BooleanField, variable, updateVariable, onSave, 'Default value')
        case 'List':
            return (
                <>
                    {renderField(ListValuesField, variable, updateVariable, onSave, 'Values')}
                    {renderField(ListDefaultField, variable, updateVariable, onSave, 'Default value')}
                </>
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
}

export const VariableForm = ({
    variable,
    updateVariable,
    onSave,
    modalType,
    onTypeChange,
}: VariableFormProps): JSX.Element => {
    return (
        <div className="gap-4 flex flex-col">
            <LemonField.Pure
                label="Name"
                className="gap-1"
                info="Variable name must be alphanumeric and can only contain spaces and underscores"
            >
                <LemonInput
                    placeholder="Name"
                    value={variable.name}
                    onChange={(value) => {
                        const filteredValue = value.replace(/[^a-zA-Z0-9\s_]/g, '')
                        updateVariable({ ...variable, name: filteredValue })
                    }}
                />
                {modalType === 'new' && variable.name.length > 0 && (
                    <span className="text-xs">{`Use this variable by referencing {variables.${getCodeName(variable.name)}}.`}</span>
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
            {renderVariableSpecificFields(variable, updateVariable, onSave)}
        </div>
    )
}
