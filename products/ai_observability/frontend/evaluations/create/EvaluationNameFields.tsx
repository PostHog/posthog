import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'

/** The name people see on results and reports, the folder it lives in, and an optional note. */
export function EvaluationNameFields(): JSX.Element | null {
    const [descriptionOpen, setDescriptionOpen] = useState(false)
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationName, setEvaluationDescription, setEvaluationDirectory } = useActions(llmEvaluationLogic)
    const { evaluationDirectories, evaluationDirectoriesLoading } = useValues(llmEvaluationsLogic())

    if (!evaluation) {
        return null
    }

    return (
        // Both fields share the same label style, so the name input and the folder picker line up.
        <div className="grid grid-cols-1 gap-x-4 gap-y-2 items-start @min-[40rem]/evaluation:grid-cols-[minmax(0,1fr)_14rem]">
            <div className="flex flex-col gap-2 min-w-0">
                <LemonField.Pure label="Name" htmlFor="llma-evaluation-create-name">
                    <LemonInput
                        id="llma-evaluation-create-name"
                        value={evaluation.name}
                        onChange={setEvaluationName}
                        placeholder="For example, Answer is grounded in the docs"
                        maxLength={100}
                        autoFocus={!evaluation.name}
                        data-attr="llma-evaluation-create-name"
                    />
                </LemonField.Pure>
                {/* An empty field waits behind this button, so it takes no room. */}
                {descriptionOpen || evaluation.description ? (
                    <LemonField.Pure label="Description (optional)" htmlFor="llma-evaluation-create-description">
                        <LemonTextArea
                            id="llma-evaluation-create-description"
                            value={evaluation.description || ''}
                            onChange={(value) => {
                                // Clearing the text keeps the field open while people type.
                                setDescriptionOpen(true)
                                setEvaluationDescription(value)
                            }}
                            placeholder="What it checks and when to use it, for your teammates"
                            maxLength={500}
                            minRows={1}
                            autoFocus={descriptionOpen}
                            data-attr="llma-evaluation-create-description"
                        />
                    </LemonField.Pure>
                ) : (
                    <div>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconPlus />}
                            onClick={() => setDescriptionOpen(true)}
                            data-attr="llma-evaluation-create-add-description"
                        >
                            Add description
                        </LemonButton>
                    </div>
                )}
            </div>
            <LemonField.Pure label="Folder">
                <LemonSelect<string | null>
                    value={evaluation.directory_id ?? null}
                    onChange={setEvaluationDirectory}
                    loading={evaluationDirectoriesLoading}
                    options={[
                        { value: null, label: 'Top level' },
                        ...evaluationDirectories.map((directory) => ({
                            value: directory.id,
                            label: directory.name,
                        })),
                    ]}
                    fullWidth
                    data-attr="llma-evaluation-create-folder"
                />
            </LemonField.Pure>
        </div>
    )
}
