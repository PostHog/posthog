import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { interProjectDuplicationLogic } from './interProjectDuplicationLogic'

export function InterProjectDuplicationModal(): JSX.Element {
    const { isModalOpen, request, destinationTeamId, duplicationResultLoading, teamOptions } =
        useValues(interProjectDuplicationLogic)
    const { closeModal, setDestinationTeamId, submitDuplication } = useActions(interProjectDuplicationLogic)

    const resourceLabel = request?.resourceName
        ? `"${request.resourceName}"`
        : (request?.resourceKind?.toLowerCase() ?? 'resource')

    return (
        <LemonModal
            title={`Copy ${request?.resourceKind?.toLowerCase() ?? 'resource'} to another project`}
            isOpen={isModalOpen}
            onClose={closeModal}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={duplicationResultLoading ? 'Copying...' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitDuplication}
                        loading={duplicationResultLoading}
                        disabledReason={!destinationTeamId ? 'Select a destination project' : undefined}
                    >
                        Copy
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <p>
                    Copy {resourceLabel} and its dependencies to another project in your organization. The original will
                    not be modified.
                </p>
                <div>
                    <label className="font-semibold leading-6 block mb-1">Destination project</label>
                    <LemonSelect
                        fullWidth
                        placeholder="Select a project"
                        value={destinationTeamId}
                        onChange={(value) => setDestinationTeamId(value)}
                        options={teamOptions}
                    />
                </div>
                {teamOptions.length === 0 && (
                    <p className="text-muted text-sm">
                        There are no other projects in your organization to copy to. Create another project first.
                    </p>
                )}
            </div>
        </LemonModal>
    )
}
