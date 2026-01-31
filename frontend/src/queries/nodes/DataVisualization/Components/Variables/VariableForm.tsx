import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { Variable, VariableType } from '../../types'
import {
    BooleanField,
    DateField,
    ListDefaultField,
    ListValuesField,
    NumberField,
    StringField,
    VARIABLE_TYPE_OPTIONS,
    getCodeName,
} from './VariableFields'

const renderVariableSpecificFields = (
    variable: Variable,
    updateVariable: (variable: Variable) => void,
    onSave: () => void
): JSX.Element => {
    const fieldProps = { variable, updateVariable, onSave }

    if (variable.type === 'String') {
        return (
            <LemonField.Pure label="Default value" className="gap-1">
                <StringField {...fieldProps} />
            </LemonField.Pure>
        )
    }

    if (variable.type === 'Number') {
        return (
            <LemonField.Pure label="Default value" className="gap-1">
                <NumberField {...fieldProps} />
            </LemonField.Pure>
        )
    }

    if (variable.type === 'Boolean') {
        return (
            <LemonField.Pure label="Default value" className="gap-1">
                <BooleanField {...fieldProps} />
            </LemonField.Pure>
        )
    }

    if (variable.type === 'List') {
        return (
            <>
                <LemonField.Pure label="Values" className="gap-1">
                    <ListValuesField {...fieldProps} />
                </LemonField.Pure>
                <LemonField.Pure label="Default value" className="gap-1">
                    <ListDefaultField {...fieldProps} />
                </LemonField.Pure>
            </>
        )
    }

    if (variable.type === 'Date') {
        return (
            <LemonField.Pure label="Default value" className="gap-1">
                <DateField {...fieldProps} />
            </LemonField.Pure>
        )
    }

    throw new Error(`Unsupported variable type: ${(variable as Variable).type}`)
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
