import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { VARIABLE_INSIGHT_COLUMNS } from 'scenes/data-management/variables/insightColumns'

import { VariableType } from '../../types'
import { VariableForm } from './VariableForm'
import { variableDataLogic } from './variableDataLogic'
import { variableModalLogic } from './variableModalLogic'

export const NewVariableModal = (): JSX.Element => {
    const { closeModal, updateVariable, save, openNewVariableModal, changeTypeExistingVariable } =
        useActions(variableModalLogic)
    const { isModalOpen, variable, modalType, insightsUsingVariable, insightsLoading } = useValues(variableModalLogic)
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

    const handleTypeChange = (variableType: VariableType): void => {
        if (modalType === 'new') {
            openNewVariableModal(variableType)
        } else {
            changeTypeExistingVariable(variableType)
        }
    }

    return (
        <LemonModal
            title={title}
            isOpen={isModalOpen}
            onClose={closeModal}
            maxWidth={modalType === 'existing' && insightsUsingVariable.length > 0 ? '60rem' : '30rem'}
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
            <VariableForm
                variable={variable}
                updateVariable={updateVariable}
                onSave={save}
                modalType={modalType}
                onTypeChange={handleTypeChange}
            />

            {modalType === 'existing' && (
                <div className="mt-4">
                    <h3 className="text-base font-semibold mb-2">Insights using this variable</h3>
                    <LemonTable
                        loading={insightsLoading}
                        dataSource={insightsUsingVariable}
                        columns={VARIABLE_INSIGHT_COLUMNS}
                        rowKey="id"
                        emptyState="No insights use this variable"
                        size="small"
                    />
                </div>
            )}
        </LemonModal>
    )
}
