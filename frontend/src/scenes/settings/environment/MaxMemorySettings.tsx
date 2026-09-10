import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { projectLogic } from 'scenes/projectLogic'

import { CORE_MEMORY_MAX_CHARACTERS, maxSettingsLogic } from './maxSettingsLogic'

export function MaxMemorySettings(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { isLoading, isUpdating, coreMemoryLoadError, coreMemoryOverLimit } = useValues(maxSettingsLogic)
    const { loadCoreMemory, trimCoreMemoryToFit } = useActions(maxSettingsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <Form
            logic={maxSettingsLogic}
            formKey="coreMemoryForm"
            enableFormOnSubmit
            className="w-full deprecated-space-y-4"
        >
            <p className="max-w-160 text-sm text-secondary mb-4">
                When memory exceeds 5,000 characters, only the first and last 2,500 characters are visible to PostHog
                AI. The maximum memory size is 10,000 characters.
            </p>
            {currentProjectLoading || isLoading ? (
                <div className="gap-2 flex flex-col">
                    <LemonSkeleton className="h-6 w-32" />
                    <LemonSkeleton className="h-16" />
                </div>
            ) : coreMemoryLoadError ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => loadCoreMemory() }}
                    className="max-w-160"
                >
                    Could not load PostHog AI's memory. This does not mean your memory is empty. Your saved memory is
                    safe. {coreMemoryLoadError}
                </LemonBanner>
            ) : (
                <>
                    {coreMemoryOverLimit && (
                        <LemonBanner
                            type="warning"
                            action={{
                                children: 'Trim to fit',
                                onClick: () => trimCoreMemoryToFit(),
                                disabledReason: restrictedReason,
                            }}
                            className="max-w-160"
                        >
                            This memory is over the {CORE_MEMORY_MAX_CHARACTERS.toLocaleString()}-character limit and
                            can't be saved until it fits. Trimming keeps the first{' '}
                            {CORE_MEMORY_MAX_CHARACTERS.toLocaleString()} characters.
                        </LemonBanner>
                    )}
                    <LemonField name="text" label="PostHog AI's memory">
                        <LemonTextArea
                            id="product-description-textarea" // Slightly dirty ID for .focus() elsewhere
                            placeholder={`What should PostHog AI know about ${
                                currentProject ? currentProject.name : 'your company or this product'
                            }?`}
                            maxLength={CORE_MEMORY_MAX_CHARACTERS}
                            maxRows={5}
                            disabled={!!restrictedReason}
                        />
                    </LemonField>
                </>
            )}
            <LemonButton
                type="primary"
                htmlType="submit"
                disabledReason={
                    !currentProject || isLoading
                        ? 'Loading project and memory...'
                        : coreMemoryLoadError
                          ? 'Memory could not be loaded'
                          : coreMemoryOverLimit
                            ? 'Memory is over the character limit. Trim it to fit first.'
                            : restrictedReason
                }
                loading={isUpdating}
            >
                Save memory
            </LemonButton>
        </Form>
    )
}
