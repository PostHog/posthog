import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { NotebookNodeAttributeProperties } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { inferGenUIInputs } from './genUIInputInference'
import { validateGenUIInputs } from './genUIInputs'
import type { NotebookNodeGenUIAttributes } from './NotebookNodeGenUI'
import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'

export function NotebookNodeGenUISettings({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeGenUIAttributes>): JSX.Element {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { isEditable, notebookLogic } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId
    const inferredInputs = inferGenUIInputs(
        notebookLogic.values.content,
        attributes.nodeId,
        attributes.prompt ?? '',
        attributes.inputs ?? ''
    )
    const inputValidation = validateGenUIInputs(inferredInputs.serialized)
    const logic = notebookNodeGenUILogic({
        notebookShortId,
        nodeId: attributes.nodeId,
        legacyCanvasId: attributes.id,
        prompt: attributes.prompt ?? '',
        inputs: inputValidation.names,
        serializedInputs: inferredInputs.serialized,
        persistedInputs: attributes.inputs ?? '',
        inputValidationError: inputValidation.error,
        isEditable,
        getContent: () => notebookLogic.values.content,
        updateAttributes,
    })
    const { error, isGenerating, isRefreshingInputs, mutationInFlight, status } = useValues(logic)
    const { ensureVisualization, regenerateVisualization } = useActions(logic)
    const unavailableInputs = status?.input_states.filter((input) => input.input_status !== 'ready') ?? []
    const isWorking = mutationInFlight || isRefreshingInputs

    return (
        <div className="flex flex-col gap-3 p-3">
            <div>
                <LemonLabel>Prompt</LemonLabel>
                <LemonTextArea
                    value={attributes.prompt ?? ''}
                    onChange={(value) => {
                        const nextPrompt = value || ''
                        const nextInputs = inferGenUIInputs(
                            notebookLogic.values.content,
                            attributes.nodeId,
                            nextPrompt,
                            attributes.inputs ?? ''
                        )
                        updateAttributes({ prompt: nextPrompt || undefined, inputs: nextInputs.serialized })
                    }}
                    placeholder="Describe the custom visualization you want to generate."
                    minRows={5}
                    autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                    disabled={!isEditable}
                />
            </div>
            {inferredInputs.names.length > 0 ? (
                <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                    <span>Using</span>
                    {inferredInputs.names.map((name) => (
                        <LemonTag key={name} size="small">
                            {name}
                        </LemonTag>
                    ))}
                    <span>from the cells above.</span>
                </div>
            ) : null}
            <LemonButton
                type="primary"
                onClick={() => (status ? regenerateVisualization() : ensureVisualization())}
                loading={isWorking}
                disabledReason={
                    isWorking
                        ? 'Visualization generation is already running'
                        : !(attributes.prompt ?? '').trim()
                          ? 'Add a prompt first'
                          : inputValidation.error || undefined
                }
            >
                {status || attributes.id ? 'Regenerate visualization' : 'Generate visualization'}
            </LemonButton>
            {unavailableInputs.length > 0 ? (
                <div className="text-xs text-muted">
                    The visualization will run these dataframes first:{' '}
                    {unavailableInputs.map((input) => input.name).join(', ')}
                </div>
            ) : null}
            {error ? <div className="text-xs text-danger">{error}</div> : null}
            {isRefreshingInputs ? (
                <div className="text-xs text-muted">Required dataframe cells are running.</div>
            ) : isGenerating ? (
                <div className="text-xs text-muted">Generation is running in the background.</div>
            ) : null}
        </div>
    )
}
