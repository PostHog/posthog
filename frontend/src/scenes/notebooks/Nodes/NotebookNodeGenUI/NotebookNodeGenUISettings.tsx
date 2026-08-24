import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheck, IconClock, IconCode, IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { dayjs } from 'lib/dayjs'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import type { GenUIVersionApi } from 'products/notebooks/frontend/generated/api.schemas'

import { NotebookNodeAttributeProperties } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { inferGenUIInputs } from './genUIInputInference'
import { validateGenUIInputs } from './genUIInputs'
import { GenUISourceModal } from './GenUISourceModal'
import type { NotebookNodeGenUIAttributes } from './NotebookNodeGenUI'
import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'

function versionPrompt(version: GenUIVersionApi): string | null {
    const prompt = version.prompt?.trim()
    if (!prompt) {
        return null
    }
    return prompt.split('\n')[0].slice(0, 80)
}

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
    const {
        error,
        isRefreshingData,
        isRefreshingInputs,
        isRegenerating,
        isSwitchingVersion,
        mutationInFlight,
        status,
        versions,
        versionsLoading,
    } = useValues(logic)
    const {
        ensureVisualization,
        loadGenUIVersions,
        openSource,
        regenerateVisualization,
        restoreVersion,
        runVisualization,
    } = useActions(logic)
    const unavailableInputs = status?.input_states.filter((input) => input.input_status !== 'ready') ?? []
    const isWorking = mutationInFlight || isRefreshingInputs || isRefreshingData || isRegenerating || isSwitchingVersion
    const hasSource = Boolean(status?.source_version_id)
    const commonDisabledReason = isWorking
        ? 'Wait for the current visualization update to finish'
        : !(attributes.prompt ?? '').trim()
          ? 'Add a prompt first'
          : inputValidation.error || undefined

    const confirmRegeneration = (): void => {
        LemonDialog.open({
            title: 'Regenerate visualization?',
            content:
                'This generates new visualization code and uses AI credits. Refresh data instead if only the dataframe results changed.',
            primaryButton: {
                children: 'Regenerate',
                onClick: regenerateVisualization,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const confirmVersion = (version: GenUIVersionApi): void => {
        LemonDialog.open({
            title: 'Use this visualization version?',
            content: `This switches to the version from ${dayjs(version.created_at).format(
                'MMM D, YYYY [at] h:mm A'
            )}. Your current version stays in history.`,
            primaryButton: {
                children: 'Use version',
                onClick: () => restoreVersion(version.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const versionItems = versionsLoading
        ? [{ label: 'Loading versions…', disabledReason: 'Loading version history' }]
        : versions.length > 0
          ? versions.map((version) => ({
                key: version.id,
                label: (
                    <div className="min-w-0 max-w-72 py-0.5">
                        <div className="flex items-center justify-between gap-2">
                            <span>{dayjs(version.created_at).format('MMM D, YYYY · h:mm A')}</span>
                            {version.is_current ? <span className="text-success">Current</span> : null}
                        </div>
                        {versionPrompt(version) ? (
                            <div className="truncate text-xs text-muted">{versionPrompt(version)}</div>
                        ) : null}
                    </div>
                ),
                icon: version.is_current ? <IconCheck /> : undefined,
                disabledReason: version.is_current
                    ? 'This version is current'
                    : isWorking
                      ? 'Wait for the current visualization update to finish'
                      : undefined,
                onClick: version.is_current || isWorking ? undefined : () => confirmVersion(version),
            }))
          : [{ label: 'No previous versions', disabledReason: 'Generate a visualization to create a version' }]

    return (
        <>
            <div className="flex flex-col gap-3 p-3">
                <div>
                    <div className="mb-1 flex min-h-6 items-center justify-between gap-2">
                        <LemonLabel>Prompt</LemonLabel>
                        {hasSource ? (
                            <div className="flex items-center gap-1">
                                <LemonButton size="xsmall" type="tertiary" icon={<IconCode />} onClick={openSource}>
                                    View source
                                </LemonButton>
                                <LemonMenu
                                    onVisibilityChange={(visible) => {
                                        if (visible) {
                                            loadGenUIVersions()
                                        }
                                    }}
                                    items={[
                                        {
                                            label: 'Versions',
                                            icon: <IconClock />,
                                            items: versionItems,
                                            closeParentPopoverOnClickInside: true,
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        icon={<IconEllipsis />}
                                        aria-label="Visualization options"
                                    />
                                </LemonMenu>
                            </div>
                        ) : null}
                    </div>
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
                <div className="flex flex-wrap items-center gap-2">
                    {hasSource ? (
                        <>
                            <LemonButton
                                type="primary"
                                onClick={runVisualization}
                                loading={isRefreshingData}
                                disabledReason={commonDisabledReason}
                            >
                                Refresh data
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                onClick={confirmRegeneration}
                                loading={isRegenerating}
                                disabledReason={commonDisabledReason}
                                tooltip="Generate new visualization code using AI credits."
                            >
                                Regenerate
                            </LemonButton>
                        </>
                    ) : (
                        <LemonButton
                            type="primary"
                            onClick={ensureVisualization}
                            loading={isRegenerating}
                            disabledReason={commonDisabledReason}
                        >
                            Generate visualization
                        </LemonButton>
                    )}
                </div>
                {unavailableInputs.length > 0 ? (
                    <div className="text-xs text-muted">
                        The visualization will run these dataframes first:{' '}
                        {unavailableInputs.map((input) => input.name).join(', ')}
                    </div>
                ) : null}
                {error ? <div className="text-xs text-danger">{error}</div> : null}
                {isRefreshingInputs ? (
                    <div className="text-xs text-muted">Required dataframe cells are running.</div>
                ) : isSwitchingVersion ? (
                    <div className="text-xs text-muted">Switching visualization version.</div>
                ) : isRefreshingData ? (
                    <div className="text-xs text-muted">Refreshing saved dataframe rows.</div>
                ) : isRegenerating ? (
                    <div className="text-xs text-muted">Generating new visualization code.</div>
                ) : null}
            </div>
            <GenUISourceModal logic={logic} />
        </>
    )
}
