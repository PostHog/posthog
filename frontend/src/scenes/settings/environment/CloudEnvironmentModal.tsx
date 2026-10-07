import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
} from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { SandboxEnvironmentNetworkAccessLevelEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { NETWORK_ACCESS_COPY } from './cloudEnvironmentNetworkAccess'
import { cloudEnvironmentsLogic } from './cloudEnvironmentsLogic'
import { cloudImagesLogic } from './cloudImagesLogic'

export function CloudEnvironmentModal(): JSX.Element | null {
    const { draft, draftSaving, draftError } = useValues(cloudEnvironmentsLogic)
    const { updateDraft, closeDraft, saveDraft } = useActions(cloudEnvironmentsLogic)
    const { readyImages, unavailable: imagesUnavailable } = useValues(cloudImagesLogic)

    if (!draft) {
        return null
    }

    return (
        <LemonModal
            isOpen
            onClose={closeDraft}
            title={draft.id ? 'Edit environment' : 'New environment'}
            description="Cloud runs start in a sandbox. An environment sets which repositories it applies to and what the sandbox can reach."
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
                        onClick={saveDraft}
                        loading={draftSaving}
                        disabledReason={draftError ?? undefined}
                        data-attr="cloud-environment-save"
                    >
                        {draft.id ? 'Save' : 'Create environment'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="cloud-environment-name">Name</LemonLabel>
                    <LemonInput
                        id="cloud-environment-name"
                        value={draft.name}
                        onChange={(name) => updateDraft({ name })}
                        placeholder="For example: Web app"
                        autoFocus
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
                <div className="flex flex-col gap-1">
                    <LemonLabel info="Leave empty to use this environment for any repository.">Repositories</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={draft.repositories}
                        onChange={(repositories) => updateDraft({ repositories })}
                        placeholder="Type org/repo and press Enter"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Network access</LemonLabel>
                    <LemonRadio
                        value={draft.network_access_level}
                        onChange={(network_access_level) => updateDraft({ network_access_level })}
                        options={Object.values(SandboxEnvironmentNetworkAccessLevelEnumApi).map((level) => ({
                            value: level,
                            label: NETWORK_ACCESS_COPY[level].label,
                            description: NETWORK_ACCESS_COPY[level].description,
                        }))}
                    />
                </div>
                {imagesUnavailable ? null : (
                    <div className="flex flex-col gap-1">
                        <LemonLabel info="Runs that use this environment start from this image.">Image</LemonLabel>
                        <LemonSelect
                            value={draft.custom_image_id}
                            onChange={(custom_image_id) => updateDraft({ custom_image_id })}
                            options={[
                                { value: null, label: 'Default image' },
                                ...readyImages.map((image) => ({ value: image.id, label: image.name })),
                            ]}
                            fullWidth
                        />
                    </div>
                )}
                {draft.network_access_level === SandboxEnvironmentNetworkAccessLevelEnumApi.Custom ? (
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Allowed domains</LemonLabel>
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                value={draft.allowed_domains}
                                onChange={(allowed_domains) => updateDraft({ allowed_domains })}
                                placeholder="Type a domain, such as api.example.com, and press Enter"
                            />
                        </div>
                        <LemonCheckbox
                            checked={draft.include_default_domains}
                            onChange={(include_default_domains) => updateDraft({ include_default_domains })}
                            label="Also allow the trusted package sources (GitHub, npm, PyPI)"
                        />
                    </div>
                ) : null}
            </div>
        </LemonModal>
    )
}
