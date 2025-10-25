import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { ExperimentHoldoutType } from '~/types'

import { NEW_HOLDOUT, holdoutsLogic } from './holdoutsLogic'

export function Holdouts(): JSX.Element {
    const { holdouts, holdoutsLoading, holdout } = useValues(holdoutsLogic)
    const { createHoldout, deleteHoldout, setHoldout, updateHoldout } = useActions(holdoutsLogic)

    const [isHoldoutModalOpen, setIsHoldoutModalOpen] = useState(false)
    const [editingHoldout, setEditingHoldout] = useState<ExperimentHoldoutType | null>(null)

    const openEditModal = (holdout: ExperimentHoldoutType): void => {
        setEditingHoldout(holdout)
        setHoldout(holdout)
        setIsHoldoutModalOpen(true)
    }

    const openCreateModal = (): void => {
        setEditingHoldout(null)
        setHoldout({ ...NEW_HOLDOUT })
        setIsHoldoutModalOpen(true)
    }

    const closeModal = (): void => {
        setIsHoldoutModalOpen(false)
        setEditingHoldout(null)
    }

    const getDisabledReason = (): string | undefined => {
        if (!holdout.name) {
            return 'Name is required'
        }
        if (
            holdout.filters?.[0]?.rollout_percentage === undefined ||
            holdout.filters?.[0]?.rollout_percentage === null
        ) {
            return 'Rollout percentage is required'
        }
        if (holdout.filters[0].rollout_percentage < 0 || holdout.filters[0].rollout_percentage > 100) {
            return 'Rollout percentage should be between 0 and 100'
        }
    }

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: (name: string) => <div className="font-semibold">{name}</div>,
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
        },
        {
            title: 'Rollout Percentage',
            dataIndex: 'filters',
            key: 'rollout',
            render: (filters: ExperimentHoldoutType['filters']) => {
                const percentage = filters?.[0]?.rollout_percentage || 0
                return <div>{percentage} %</div>
            },
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_: any, record: ExperimentHoldoutType) => (
                <div className="flex gap-2">
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        icon={<IconPencil />}
                        onClick={() => openEditModal(record)}
                    />
                    <LemonButton
                        type="secondary"
                        icon={<IconTrash />}
                        size="xsmall"
                        status="danger"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Delete this holdout?',
                                content: (
                                    <div className="text-sm">
                                        Are you sure you want to delete the holdout <b>"{record.name}"</b>? This action
                                        cannot be undone.
                                    </div>
                                ),
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    status: 'danger',
                                    onClick: () => deleteHoldout(record.id),
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                    />
                </div>
            ),
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            <LemonModal
                isOpen={isHoldoutModalOpen}
                onClose={closeModal}
                title={editingHoldout ? 'Edit holdout' : 'Add holdout'}
                footer={
                    <>
                        <LemonButton onClick={closeModal}>Cancel</LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                if (editingHoldout) {
                                    updateHoldout(editingHoldout.id, holdout)
                                } else {
                                    createHoldout()
                                }
                                closeModal()
                            }}
                            disabledReason={getDisabledReason()}
                        >
                            {editingHoldout ? 'Update' : 'Save'}
                        </LemonButton>
                    </>
                }
            >
                <div className="deprecated-space-y-4">
                    <div>
                        <LemonLabel>Name</LemonLabel>
                        <LemonInput
                            value={holdout.name}
                            onChange={(name) => setHoldout({ name })}
                            placeholder="e.g. 'Frontend holdout group 1'"
                        />
                    </div>
                    <div>
                        <LemonLabel>Description</LemonLabel>
                        <LemonInput
                            value={holdout.description || ''}
                            onChange={(description) => setHoldout({ description })}
                        />
                    </div>
                    <div>
                        <LemonDivider />
                        <LemonBanner type="info">
                            <div className="deprecated-space-y-2">
                                <div>
                                    Specify the percentage population that should be included in this holdout group.
                                    This is stable across experiments.
                                </div>
                            </div>
                        </LemonBanner>
                        <div className="mt-4 flex flex-wrap items-center gap-1">
                            Roll out to{' '}
                            <LemonSlider
                                value={holdout.filters?.[0]?.rollout_percentage || 100}
                                onChange={(rollout_percentage) =>
                                    setHoldout({
                                        filters: [{ properties: [], rollout_percentage }],
                                    })
                                }
                                min={0}
                                max={100}
                                step={1}
                                className="ml-1.5 w-20"
                            />
                            <LemonInput
                                data-attr="rollout-percentage"
                                type="number"
                                className="ml-2 mr-1.5 max-w-30"
                                value={holdout.filters?.[0]?.rollout_percentage || 100}
                                onChange={(rollout_percentage) =>
                                    setHoldout({
                                        filters: [{ properties: [], rollout_percentage }],
                                    })
                                }
                                min={0}
                                max={100}
                                step="any"
                                suffix={<span>%</span>}
                            />
                            of <b>total users.</b>
                        </div>
                    </div>
                </div>
            </LemonModal>

            <LemonBanner type="info">
                <div className="deprecated-space-y-2">
                    <div>
                        Holdouts are stable groups of users excluded from experiment variations.They act as a baseline,
                        helping you see how users behave without any changes applied. This lets you directly compare
                        their behavior to those exposed to the experiment variations. Once a holdout is configured, you
                        can apply it to an experiment during creation.
                    </div>
                </div>
            </LemonBanner>

            <LemonTable
                emptyState={
                    <div className="py-4 text-secondary text-sm text-center">
                        You have not created any holdouts yet.
                    </div>
                }
                loading={holdoutsLoading}
                dataSource={holdouts}
                columns={columns as LemonTableColumns<ExperimentHoldoutType>}
            />
            <LemonButton type="primary" onClick={openCreateModal} data-attr="add-holdout">
                New holdout
            </LemonButton>
        </div>
    )
}
