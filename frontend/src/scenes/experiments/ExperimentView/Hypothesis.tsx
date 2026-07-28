import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

export function Hypothesis(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment } = useActions(experimentLogic)
    const { openDescriptionModal, closeDescriptionModal } = useActions(modalsLogic)
    const { isDescriptionModalOpen } = useValues(modalsLogic)

    const [tempDescription, setTempDescription] = useState(experiment.description || '')

    useEffect(() => {
        setTempDescription(experiment.description || '')
    }, [experiment.description])

    return (
        <div className="border rounded bg-surface-primary p-4">
            <div className="flex items-center gap-2 mb-2">
                <h2 className="font-semibold text-base m-0">Hypothesis</h2>
                <LemonButton type="secondary" size="xsmall" icon={<IconPencil />} onClick={openDescriptionModal} />
            </div>
            {experiment.description ? (
                <p className="m-0 whitespace-pre-wrap">{experiment.description}</p>
            ) : (
                <p className="m-0 text-secondary italic">Add your hypothesis for this test</p>
            )}

            <LemonModal
                isOpen={isDescriptionModalOpen}
                onClose={closeDescriptionModal}
                title="Edit hypothesis"
                footer={
                    <div className="flex items-center gap-2 justify-end">
                        <LemonButton type="secondary" onClick={closeDescriptionModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                updateExperiment({ description: tempDescription })
                                closeDescriptionModal()
                            }}
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <LemonTextArea
                    className="w-full"
                    value={tempDescription}
                    onChange={(value) => setTempDescription(value)}
                    placeholder="Add your hypothesis for this test"
                    minRows={6}
                    maxLength={3000}
                />
            </LemonModal>
        </div>
    )
}
