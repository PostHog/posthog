import {
    LemonButton,
    LemonCalendarSelectInput,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useState } from 'react'

import { DateVariable, Variable, VariableType } from '../../types'
import { variableModalLogic } from './variableModalLogic'

const renderVariableSpecificFields = (
    variable: Variable,
    updateVariable: (variable: Variable) => void
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
                <NewVariableCalendar variable={variable} updateVariable={updateVariable} />
            </LemonField.Pure>
        )
    }

    throw new Error(`Unsupported variable type: ${(variable as Variable).type}`)
}

const NewVariableCalendar = ({
    variable,
    updateVariable,
}: {
    variable: DateVariable
    updateVariable: (variable: DateVariable) => void
}): JSX.Element => {
    const [calendarTime, setCalendarTime] = useState(false)

    return (
        <LemonCalendarSelectInput
            value={variable.default_value ? dayjs(variable.default_value) : null}
            onChange={(date) =>
                updateVariable({ ...variable, default_value: date?.format('YYYY-MM-DD HH:mm:00') ?? '' })
            }
            showTimeToggle={true}
            granularity={calendarTime ? 'minute' : 'day'}
            onToggleTime={(value) => setCalendarTime(value)}
        />
    )
}

export const NewVariableModal = (): JSX.Element => {
    const { closeModal, updateVariable, save, openNewVariableModal } = useActions(variableModalLogic)
    const { isModalOpen, variable, modalType } = useValues(variableModalLogic)

    const title = modalType === 'new' ? `New ${variable.type} variable` : `Editing ${variable.name}`

    return (
        <LemonModal
            title={title}
            isOpen={isModalOpen}
            onClose={closeModal}
            maxWidth="30rem"
            footer={
                <div className="flex flex-1 justify-end gap-2">
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => save()}>
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="gap-4 flex flex-col">
                <LemonField.Pure label="Name" className="gap-1">
                    <LemonInput
                        placeholder="Name"
                        value={variable.name}
                        onChange={(value) => updateVariable({ ...variable, name: value })}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Type" className="gap-1">
                    <LemonSelect
                        value={variable.type}
                        onChange={(value) => openNewVariableModal(value as VariableType)}
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
                {renderVariableSpecificFields(variable, updateVariable)}
            </div>
        </LemonModal>
    )
}
