import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSegmentedButton, LemonTextArea } from '@posthog/lemon-ui'

import { cloudImagesLogic } from './cloudImagesLogic'

export function CloudImageModal(): JSX.Element | null {
    const { draft, draftSaving, draftError } = useValues(cloudImagesLogic)
    const { updateDraft, closeDraft, createImage } = useActions(cloudImagesLogic)

    if (!draft) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={closeDraft}
            title="New image"
            description="A builder agent installs your tools in a sandbox and saves the result as an image. Cloud runs that use it start with those tools ready."
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeDraft}
                        disabledReason={draftSaving ? 'Saving' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={createImage}
                        loading={draftSaving}
                        disabledReason={draftError ?? undefined}
                        data-attr="cloud-image-create"
                    >
                        Start building
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="cloud-image-name">Name</LemonLabel>
                    <LemonInput
                        id="cloud-image-name"
                        value={draft.name}
                        onChange={(name) => updateDraft({ name })}
                        placeholder="For example: Node 22 with ripgrep"
                        autoFocus
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="cloud-image-description">What the image needs</LemonLabel>
                    <LemonTextArea
                        id="cloud-image-description"
                        value={draft.description}
                        onChange={(description) => updateDraft({ description })}
                        minRows={3}
                        placeholder="For example: Node 22, pnpm, and ripgrep. Run pnpm install for the web app."
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel
                        htmlFor="cloud-image-repository"
                        info="The builder agent clones it to check that its dependencies install."
                        showOptional
                    >
                        Repository
                    </LemonLabel>
                    <LemonInput
                        id="cloud-image-repository"
                        value={draft.repository}
                        onChange={(repository) => updateDraft({ repository })}
                        placeholder="org/repo"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Who can use it</LemonLabel>
                    <LemonSegmentedButton
                        value={draft.private ? 'private' : 'project'}
                        onChange={(value) => updateDraft({ private: value === 'private' })}
                        options={[
                            { value: 'private', label: 'Only you' },
                            { value: 'project', label: 'Everyone in this project' },
                        ]}
                        size="small"
                    />
                </div>
            </div>
        </LemonModal>
    )
}
