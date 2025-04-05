import { LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import { maxSettingsLogic } from './maxSettingsLogic'

export function MaxMemorySettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { isLoading, isUpdating } = useValues(maxSettingsLogic)

    return (
        <Form
            logic={maxSettingsLogic}
            formKey="coreMemoryForm"
            enableFormOnSubmit
            className="w-full deprecated-space-y-4"
        >
            {currentTeamLoading || isLoading ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="w-32 h-6" />
                    <LemonSkeleton className="h-16" />
                </div>
            ) : (
                <LemonField name="text" label="Max’s memory">
                    <LemonTextArea
                        id="product-description-textarea" // Slightly dirty ID for .focus() elsewhere
                        placeholder={`What's should Max know about ${
                            currentTeam ? currentTeam.name : 'your company or this product'
                        }?`}
                        maxLength={10000}
                        maxRows={5}
                    />
                </LemonField>
            )}
            <LemonButton
                type="primary"
                htmlType="submit"
                disabledReason={!currentTeam || isLoading ? 'Loading project and memory...' : undefined}
                loading={isUpdating}
            >
                Save memory
            </LemonButton>
        </Form>
    )
}
