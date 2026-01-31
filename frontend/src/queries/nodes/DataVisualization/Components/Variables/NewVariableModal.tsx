import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel } from '~/types'

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

    const insightColumns: LemonTableColumns<QueryBasedInsightModel> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                return (
                    <LemonTableLink
                        to={urls.insightView(insight.short_id)}
                        title={name || <i>Untitled</i>}
                        description={insight.description}
                    />
                )
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: function RenderCreated(created_at: string) {
                return created_at ? (
                    <div className="whitespace-nowrap text-right">
                        <TZLabel time={created_at} />
                    </div>
                ) : (
                    <span className="text-secondary">—</span>
                )
            },
            align: 'right',
        },
        {
            title: 'Last modified',
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
        },
        {
            title: 'Last viewed',
            dataIndex: 'last_viewed_at',
            render: function renderLastViewed(last_viewed_at: string | null) {
                return (
                    <div className="whitespace-nowrap">
                        {last_viewed_at ? <TZLabel time={last_viewed_at} /> : <span className="text-muted">Never</span>}
                    </div>
                )
            },
        },
    ]

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
                        columns={insightColumns}
                        rowKey="id"
                        emptyState="No insights use this variable"
                        size="small"
                    />
                </div>
            )}
        </LemonModal>
    )
}
