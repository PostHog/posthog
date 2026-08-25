import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { NotebookNodeAttributeProperties } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { confirmGenUIGeneration } from './confirmGenUIGeneration'
import { validateGenUIInputs } from './genUIInputs'
import type { NotebookNodeGenUIAttributes } from './NotebookNodeGenUI'
import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'

export function NotebookNodeGenUISettings({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeGenUIAttributes>): JSX.Element {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { isEditable, notebookLogic } = useValues(nodeLogic)
    const inputValidation = validateGenUIInputs(attributes.inputs ?? '')
    const logic = notebookNodeGenUILogic({
        notebookShortId: notebookLogic.props.shortId,
        nodeId: attributes.nodeId,
        prompt: attributes.prompt ?? '',
        inputs: inputValidation.names,
        inputValidationError: inputValidation.error,
        isEditable,
    })
    const { error, generationInFlight, status } = useValues(logic)
    const { generateVisualization, refreshData } = useActions(logic)
    const promptId = `genui-prompt-${attributes.nodeId}`
    const inputsId = `genui-inputs-${attributes.nodeId}`
    const isBuilding = status?.lifecycle_status === 'building'
    const isWorking = generationInFlight || isBuilding
    const disabledReason = isWorking
        ? 'Wait for the visualization to finish'
        : !(attributes.prompt ?? '').trim()
          ? 'Add a prompt first'
          : inputValidation.error || undefined

    const generate = (): void => {
        if (status?.lifecycle_status === 'ready' || status?.lifecycle_status === 'failed') {
            confirmGenUIGeneration(generateVisualization)
        } else {
            generateVisualization()
        }
    }

    return (
        <div className="flex flex-col gap-3 p-3">
            <div>
                <LemonLabel htmlFor={promptId}>Prompt</LemonLabel>
                <LemonTextArea
                    id={promptId}
                    value={attributes.prompt ?? ''}
                    onChange={(value) => updateAttributes({ prompt: value || undefined })}
                    placeholder="Describe the visualization you want to generate."
                    minRows={5}
                    autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                    disabled={!isEditable}
                    className="mt-1"
                />
            </div>
            <div>
                <LemonLabel htmlFor={inputsId}>Dataframes</LemonLabel>
                <LemonTextArea
                    id={inputsId}
                    value={attributes.inputs ?? ''}
                    onChange={(value) => updateAttributes({ inputs: value || undefined })}
                    placeholder="orders, weekly_revenue"
                    minRows={2}
                    disabled={!isEditable}
                    className="mt-1"
                />
                <div className="mt-1 text-xs text-muted">Use up to four dataframe names from SQL or Python cells.</div>
            </div>
            {inputValidation.names.length > 0 ? (
                <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                    <span>Available to the visualization:</span>
                    {inputValidation.names.map((name) => (
                        <LemonTag key={name} size="small">
                            {name}
                        </LemonTag>
                    ))}
                </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
                {status?.lifecycle_status === 'ready' ? (
                    <LemonButton type="primary" onClick={refreshData} disabled={isWorking}>
                        Reload data
                    </LemonButton>
                ) : null}
                <LemonButton
                    type={status?.lifecycle_status === 'ready' ? 'secondary' : 'primary'}
                    onClick={generate}
                    loading={generationInFlight || isBuilding}
                    disabledReason={disabledReason}
                >
                    {status?.lifecycle_status === 'ready' ? 'Regenerate' : 'Generate visualization'}
                </LemonButton>
            </div>
            {inputValidation.error ? <div className="text-xs text-danger">{inputValidation.error}</div> : null}
            {error ? <div className="text-xs text-danger">{error}</div> : null}
        </div>
    )
}
