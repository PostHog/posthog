import { LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { projectLogic } from 'scenes/projectLogic'

import { maxSettingsLogic } from './maxSettingsLogic'

export function MaxMemorySettings(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { isLoading, isUpdating } = useValues(maxSettingsLogic)

    return (
        <Form
            logic={maxSettingsLogic}
            formKey="coreMemoryForm"
            enableFormOnSubmit
            className="w-full deprecated-space-y-4"
        >
            {currentProjectLoading || isLoading ? (
                <div className="gap-2 flex flex-col">
                    <LemonSkeleton className="h-6 w-32" />
                    <LemonSkeleton className="h-16" />
                </div>
            ) : (
                <LemonField name="text" label="Max’s memory">
                    <LemonTextArea
                        id="product-description-textarea" // Slightly dirty ID for .focus() elsewhere
                        placeholder={`What should Max know about ${
                            currentProject ? currentProject.name : 'your company or this product'
                        }?`}
                        maxLength={10000}
                        maxRows={5}
                    />
                </LemonField>
            )}
            <LemonButton
                type="primary"
                htmlType="submit"
                disabledReason={!currentProject || isLoading ? 'Loading project and memory...' : undefined}
                loading={isUpdating}
            >
                Save memory
            </LemonButton>
        </Form>
    )
}
