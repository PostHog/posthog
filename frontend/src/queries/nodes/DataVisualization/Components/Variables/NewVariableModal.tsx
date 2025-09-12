import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { Variable, VariableType } from '../../types'
import { VariableCalendar } from './VariableCalendar'
import { variableDataLogic } from './variableDataLogic'
import { variableModalLogic } from './variableModalLogic'

const getCodeName = (name: string): string => {
    return (
        name
            .trim()
            //  Filter out all characters that is not a letter, number or space
            .replace(/[^a-zA-Z0-9\s]/g, '')
            .replace(/\s/g, '_')
            .toLowerCase()
    )
}

const renderVariableSpecificFields = (
    variable: Variable,
    updateVariable: (variable: Variable) => void,
    onSave: () => void
): JSX.Element => {
    if (variable.type === 'String') {
        return (
            <LemonField.Pure label="Default value" className="gap-1">
                <LemonInput
                    placeholder="Default value"
                    value={variable.default_value}
                    onChange={(value) => updateVariable({ ...variable, default_value: value })}
                />
            </LemonField.Pure>
        )
    }

    if (variable.type === 'Number') {
        return (
            <LemonField.Pure label="Default value" className="gap-1">
                <LemonInput
                    placeholder="Default value"
                    type="number"
                    value={variable.default_value}
                    onChange={(value) => updateVariable({ ...variable, default_value: value ?? 0 })}
                />
            </LemonField.Pure>
        )
    }

    if (variable.type === 'Boolean') {
        return (
            <LemonField.Pure label="Default value" className="gap-1">
                <LemonSegmentedButton
                    className="w-full"
                    value={variable.default_value ? 'true' : 'false'}
                    onChange={(value) => updateVariable({ ...variable, default_value: value === 'true' })}
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
            </LemonField.Pure>
        )
    }

    if (variable.type === 'List') {
        return (
            <>
                <LemonField.Pure label="Values" className="gap-1">
                    <LemonInputSelect
                        value={variable.values}
                        onChange={(value) => updateVariable({ ...variable, values: value })}
                        placeholder="Options..."
                        mode="multiple"
                        allowCustomValues={true}
                        options={[]}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Default value" className="gap-1">
                    <LemonSelect
                        className="w-full"
                        placeholder="Select default value"
                        value={variable.default_value}
                        options={variable.values.map((n) => ({ label: n, value: n }))}
                        onChange={(value) => updateVariable({ ...variable, default_value: value ?? '' })}
                        allowClear
                        dropdownMaxContentWidth
                    />
                </LemonField.Pure>
            </>
        )
    }

    if (variable.type === 'Date') {
        return (
            <LemonField.Pure label="Default value" className="gap-1">
                <VariableCalendar
                    value={dayjs(variable.default_value)}
                    updateVariable={(date) => {
                        updateVariable({ ...variable, default_value: date })
                        // calendar is a special case to reuse LemonCalendarSelect
                        onSave()
                    }}
                />
            </LemonField.Pure>
        )
    }

    throw new Error(`Unsupported variable type: ${(variable as Variable).type}`)
}

export const NewVariableModal = (): JSX.Element => {
    const { closeModal, updateVariable, save, openNewVariableModal, changeTypeExistingVariable } =
        useActions(variableModalLogic)
    const { isModalOpen, variable, modalType } = useValues(variableModalLogic)
    const { deleteVariable } = useActions(variableDataLogic)
    const title = modalType === 'new' ? `New ${variable.type} variable` : `Editing ${variable.name}`

    const handleDelete = (): void => {
        if (variable.id) {
            LemonDialog.open({
                title: 'Delete',
                description:
                    'Are you sure you want to delete this variable? This cannot be undone. Queries that use this variable will no longer work.',
                primaryButton: {
                    status: 'danger',
                    children: 'Delete variable',
                    onClick: (): void => {
                        deleteVariable(variable.id)
                        closeModal()
                    },
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        }
    }

    return (
        <LemonModal
            title={title}
            isOpen={isModalOpen}
            onClose={closeModal}
            maxWidth="30rem"
            footer={
                variable.type !== 'Date' && (
                    <div className="flex flex-1 justify-end gap-2">
                        {modalType === 'existing' && (
                            <LemonButton type="secondary" status="danger" onClick={handleDelete}>
                                Delete variable
                            </LemonButton>
                        )}
                        <div className="flex-1" />
                        <LemonButton type="secondary" onClick={closeModal}>
                            Close
                        </LemonButton>
                        <LemonButton type="primary" onClick={() => save()}>
                            Save
                        </LemonButton>
                    </div>
                )
            }
        >
            <div className="gap-4 flex flex-col">
                <LemonField.Pure label="Name" className="gap-1">
                    <LemonInput
                        placeholder="Name"
                        value={variable.name}
                        onChange={(value) => updateVariable({ ...variable, name: value })}
                    />
                    {modalType === 'new' && variable.name.length > 0 && (
                        <span className="text-xs">{`Use this variable by referencing {variables.${getCodeName(variable.name)}}.`}</span>
                    )}
                </LemonField.Pure>
                <LemonField.Pure label="Type" className="gap-1">
                    <LemonSelect
                        value={variable.type}
                        onChange={(value) => {
                            if (modalType === 'new') {
                                openNewVariableModal(value as VariableType)
                            } else {
                                changeTypeExistingVariable(value as VariableType)
                            }
                        }}
                        options={[
                            {
                                value: 'String',
                                label: 'String',
                            },
                            {
                                value: 'Number',
                                label: 'Number',
                            },
                            {
                                value: 'Boolean',
                                label: 'Boolean',
                            },
                            {
                                value: 'List',
                                label: 'List',
                            },
                            {
                                value: 'Date',
                                label: 'Date',
                            },
                        ]}
                    />
                </LemonField.Pure>
                {renderVariableSpecificFields(variable, updateVariable, save)}
            </div>
        </LemonModal>
    )
}
