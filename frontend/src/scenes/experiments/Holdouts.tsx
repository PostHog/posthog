import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { useState } from 'react'

import { Holdout, holdoutsLogic, NEW_HOLDOUT } from './holdoutsLogic'

export function Holdouts(): JSX.Element {
    const { holdouts, holdout } = useValues(holdoutsLogic)
    const { createHoldout, deleteHoldout, setHoldout, updateHoldout } = useActions(holdoutsLogic)

    const [isHoldoutModalOpen, setIsHoldoutModalOpen] = useState(false)
    const [editingHoldout, setEditingHoldout] = useState<Holdout | null>(null)

    const openEditModal = (holdout: Holdout): void => {
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
            render: (filters: Holdout['filters']) => {
                const percentage = filters.groups?.[0]?.rollout_percentage || 0
                return <div>{percentage} %</div>
            },
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_, record: Holdout) => (
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
                        onClick={() => deleteHoldout(record.id)}
                    />
                </div>
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <LemonModal
                isOpen={isHoldoutModalOpen}
                onClose={closeModal}
                title={editingHoldout ? 'Edit Holdout' : 'Add Holdout'}
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
                        >
                            {editingHoldout ? 'Update' : 'Save'}
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-4">
                    <LemonInput
                        value={holdout.name}
                        onChange={(name) => setHoldout({ name })}
                        placeholder="Enter holdout name"
                    />
                    <LemonInput
                        value={holdout.description || ''}
                        onChange={(description) => setHoldout({ description })}
                        placeholder="Enter holdout description"
                    />
                    <div>
                        <label className="bold">Percentage</label>
                        <LemonSlider
                            min={0}
                            max={100}
                            value={holdout.filters.groups?.[0]?.rollout_percentage || 0}
                            onChange={(rollout_percentage) =>
                                setHoldout({
                                    filters: {
                                        groups: [{ properties: [], rollout_percentage }],
                                    },
                                })
                            }
                        />
                    </div>
                </div>
            </LemonModal>

            <LemonBanner type="info">
                <div className="space-y-2">
                    <div>
                        Holdouts are a stable group of users excluded from experiment variations. They serve as a
                        baseline or benchmark, providing a consistent comparison across multiple experiments. Once a
                        holdout is configured, you can apply it when creating an experiment.
                    </div>
                </div>
            </LemonBanner>

            <LemonTable dataSource={holdouts} columns={columns} />
            <LemonButton type="primary" onClick={openCreateModal} data-attr="add-holdout">
                Add holdout
            </LemonButton>
        </div>
    )
}
