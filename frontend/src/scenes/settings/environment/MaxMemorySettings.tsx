import { LemonButton, LemonCollapse, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { projectLogic } from 'scenes/projectLogic'

export function MaxMemorySettings(): JSX.Element {
    const { currentProject, currentProjectLoading } = useValues(projectLogic)
    const { updateCurrentProject } = useActions(projectLogic)

    const [description, setDescription] = useState(currentProject?.product_description || '')

    return (
        <div>
            <LemonCollapse
                className="max-w-160"
                panels={[
                    {
                        key: 'core-memory',
                        header: 'Show Memory',
                        content: (
                            <div className="space-y-4">
                                <LemonTextArea
                                    id="product-description-textarea" // Slightly dirty ID for .focus() elsewhere
                                    value={description}
                                    onChange={setDescription}
                                    disabled={currentProjectLoading}
                                    placeholder={`What's the essence of ${
                                        currentProject ? currentProject.name : 'your product'
                                    }?`}
                                    onPressCmdEnter={() => updateCurrentProject({ product_description: description })}
                                    maxLength={10000}
                                />
                                <LemonButton
                                    type="primary"
                                    onClick={() => updateCurrentProject({ product_description: description })}
                                    disabled={!currentProject || description === currentProject.product_description}
                                    loading={currentProjectLoading}
                                >
                                    Save description
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
