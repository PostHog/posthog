import { LemonButton, LemonCollapse, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { projectLogic } from 'scenes/projectLogic'

import { maxSettingsLogic } from './maxSettingsLogic'

export function MaxMemorySettings(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { isLoading, isUpdating } = useValues(maxSettingsLogic)

    return (
        <div>
            <LemonCollapse
                className="max-w-160"
                panels={[
                    {
                        key: 'core-memory',
                        header: 'Show Memory',
                        content: (
                            <Form
                                logic={maxSettingsLogic}
                                formKey="coreMemoryForm"
                                enableFormOnSubmit
                                className="w-full space-y-4"
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
                                            placeholder={`What's the essence of ${
                                                currentProject ? currentProject.name : 'your product'
                                            }?`}
                                            maxLength={10000}
                                        />
                                    </LemonField>
                                )}
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    disabledReason={
                                        !currentProject || isLoading ? 'Loading project and memory...' : undefined
                                    }
                                    loading={isUpdating}
                                >
                                    Save description
                                </LemonButton>
                            </Form>
                        ),
                    },
                ]}
            />
        </div>
    )
}
