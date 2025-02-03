import { LemonButton, LemonCollapse, LemonTextArea } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { projectLogic } from 'scenes/projectLogic'

import { maxSettingsLogic } from './maxSettingsLogic'

export function MaxMemorySettings(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { isLoading } = useValues(maxSettingsLogic)

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
                                <LemonField name="text" label="Max memory">
                                    <LemonTextArea
                                        id="product-description-textarea" // Slightly dirty ID for .focus() elsewhere
                                        placeholder={`What's the essence of ${
                                            currentProject ? currentProject.name : 'your product'
                                        }?`}
                                        maxLength={10000}
                                        disabled={isLoading || currentProjectLoading}
                                    />
                                </LemonField>
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    disabled={!currentProject}
                                    loading={isLoading}
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
