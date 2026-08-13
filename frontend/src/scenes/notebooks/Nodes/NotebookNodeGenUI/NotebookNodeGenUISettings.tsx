import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { NotebookNodeAttributeProperties } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
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
    const inputValidation = validateGenUIInputs(attributes.inputs ?? '')
    const logic = notebookNodeGenUILogic({
        notebookShortId,
        nodeId: attributes.nodeId,
        legacyCanvasId: attributes.id,
        prompt: attributes.prompt ?? '',
        inputs: inputValidation.names,
        inputValidationError: inputValidation.error,
        isEditable,
        getContent: () => notebookLogic.values.content,
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
                    onChange={(value) => updateAttributes({ prompt: value || undefined })}
                    placeholder="Describe the custom visualization you want to generate."
                    minRows={5}
                    autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                    disabled={!isEditable}
                />
            </div>
            <div>
                <LemonLabel>Dataframes</LemonLabel>
                <LemonInput
                    value={attributes.inputs ?? ''}
                    onChange={(value) => updateAttributes({ inputs: value })}
                    placeholder="pandas_df, another_df"
                    disabled={!isEditable}
                />
                <div className="mt-1 text-xs text-muted">
                    Enter up to four named outputs from SQL or Python cells. The visualization receives their saved
                    preview rows.
                </div>
            </div>
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
            {inputValidation.error ? <div className="text-xs text-danger">{inputValidation.error}</div> : null}
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
