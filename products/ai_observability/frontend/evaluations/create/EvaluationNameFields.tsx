import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

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
    // A template's description shows straight away. Otherwise the field waits behind a button, so it takes no room.
    const showDescription = descriptionOpen || !!evaluation.description

    return (
        <div className="grid grid-cols-1 gap-4 @min-[40rem]/evaluation:grid-cols-[minmax(0,1fr)_14rem]">
            <div className="flex flex-col gap-2 min-w-0">
                <div className="flex items-center justify-between gap-2">
                    <label className="font-semibold text-sm" htmlFor="llma-evaluation-create-name">
                        Name
                    </label>
                    {!showDescription && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconPlus />}
                            onClick={() => setDescriptionOpen(true)}
                            data-attr="llma-evaluation-create-add-description"
                        >
                            Add description
                        </LemonButton>
                    )}
                </div>
                <LemonInput
                    id="llma-evaluation-create-name"
                    value={evaluation.name}
                    onChange={setEvaluationName}
                    placeholder="For example, Answer is grounded in the docs"
                    maxLength={100}
                    autoFocus={!evaluation.name}
                    data-attr="llma-evaluation-create-name"
                />
                {showDescription && (
                    <div className="flex flex-col gap-1 mt-1">
                        <label className="font-semibold text-sm" htmlFor="llma-evaluation-create-description">
                            Description <span className="font-normal text-secondary">(optional)</span>
                        </label>
                        <LemonInput
                            id="llma-evaluation-create-description"
                            value={evaluation.description || ''}
                            onChange={(description) => {
                                // Keeps the field open when someone clears a description a template filled in.
                                setDescriptionOpen(true)
                                setEvaluationDescription(description)
                            }}
                            placeholder="What it checks and when to use it, for your teammates"
                            maxLength={500}
                            autoFocus={descriptionOpen && !evaluation.description}
                            data-attr="llma-evaluation-create-description"
                        />
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
