import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { ExperimentPhase } from '~/types'

import { experimentLogic } from '../experimentLogic'

export function EditPhasesModal(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { isEditPhasesModalOpen, experiment } = useValues(experimentLogic)
    const { closeEditPhasesModal, openAddPhaseModal, openEditPhaseModal } = useActions(experimentLogic)

    if (!isEnabled) {
        return null
    }

    const phases = experiment.phases || []
    const isRunning = !!experiment.start_date && !experiment.end_date

    // Build rows: if no explicit phases, show a single implicit "Main" phase
    const rows: { index: number; name: string; phase: ExperimentPhase | null }[] =
        phases.length > 0
            ? phases.map((phase, i) => ({
                  index: i + 1,
                  name: phase.name || `Phase ${i + 1}`,
                  phase,
              }))
            : experiment.start_date
              ? [
                    {
                        index: 1,
                        name: 'Main',
                        phase: {
                            start_date: experiment.start_date,
                            end_date: experiment.end_date ?? null,
                        },
                    },
                ]
              : []

    return (
        <LemonModal
            isOpen={isEditPhasesModalOpen}
            onClose={closeEditPhasesModal}
            title="Edit Phases"
            footer={
                <div className="flex justify-end w-full">
                    <LemonButton type="tertiary" onClick={closeEditPhasesModal}>
                        Close
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <LemonTable
                    dataSource={rows}
                    columns={[
                        {
                            title: '',
                            key: 'index',
                            width: 32,
                            render: (_, row) => <span className="text-secondary">{row.index}</span>,
                        },
                        {
                            title: 'NAME',
                            key: 'name',
                            render: (_, row) => row.name,
                        },
                        {
                            title: 'DATES',
                            key: 'dates',
                            render: (_, row) => {
                                if (!row.phase) {
                                    return '–'
                                }
                                const start = dayjs(row.phase.start_date).format('MMM D, YYYY')
                                const end = row.phase.end_date ? dayjs(row.phase.end_date).format('MMM D, YYYY') : null
                                return (
                                    <span>
                                        <strong>{start}</strong> to <strong>{end ?? 'now'}</strong>
                                    </span>
                                )
                            },
                        },
                        {
                            title: '',
                            key: 'actions',
                            width: 60,
                            render: (_, row) => (
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    onClick={() => {
                                        closeEditPhasesModal()
                                        openEditPhaseModal(row.index - 1)
                                    }}
                                >
                                    Edit
                                </LemonButton>
                            ),
                        },
                    ]}
                    size="small"
                    showHeader={true}
                />
                {isRunning && (
                    <div>
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => {
                                closeEditPhasesModal()
                                openAddPhaseModal()
                            }}
                        >
                            New Phase
                        </LemonButton>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
