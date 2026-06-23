import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCopy, IconInfo, IconRefresh, IconRevert } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonLabel, LemonSwitch, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { DEFAULT_GENERATED_VEGA_LITE_PROMPT, GENERATED_VEGA_LITE_SYSTEM_PROMPT } from '../generatedVegaLiteUtils'

export const GeneratedVegaLiteTab = (): JSX.Element => {
    const [showJson, setShowJson] = useState(false)
    const { chartSettings, columns, generatedVegaLiteResponseLoading, response } = useValues(dataVisualizationLogic)
    const { generateVegaLiteChart, updateChartSettings } = useActions(dataVisualizationLogic)
    const generatedSettings = chartSettings.generatedVegaLite ?? {}
    const prompt = generatedSettings.prompt ?? DEFAULT_GENERATED_VEGA_LITE_PROMPT
    const hasColumns = !!response && columns.length > 0

    const updatePrompt = (nextPrompt: string): void => {
        updateChartSettings({
            generatedVegaLite: {
                prompt: nextPrompt,
            },
        })
    }

    const submitPrompt = (): void => {
        if (hasColumns && !generatedVegaLiteResponseLoading) {
            generateVegaLiteChart()
        }
    }

    const specForJson = generatedSettings.spec ?? generatedSettings.validatedSpec

    return (
        <div className="flex flex-col gap-3 p-3">
            {!hasColumns ? <LemonBanner type="info">Run a query before generating a visualization.</LemonBanner> : null}

            {generatedSettings.validationError ? (
                <LemonBanner type="warning">Validation failed: {generatedSettings.validationError}</LemonBanner>
            ) : null}

            {generatedSettings.renderError ? (
                <LemonBanner type="warning">Render failed: {generatedSettings.renderError}</LemonBanner>
            ) : null}

            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                    <LemonLabel>User prompt</LemonLabel>
                    <Tooltip
                        interactive
                        title={<div className="max-w-96 text-xs">{GENERATED_VEGA_LITE_SYSTEM_PROMPT}</div>}
                    >
                        <LemonButton type="tertiary" size="xsmall" icon={<IconInfo />}>
                            Show system prompt
                        </LemonButton>
                    </Tooltip>
                </div>
                <LemonTextArea
                    value={prompt}
                    minRows={3}
                    onChange={updatePrompt}
                    onKeyDown={(event) => {
                        if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                            event.preventDefault()
                            submitPrompt()
                        }
                    }}
                    data-attr="generated-vega-lite-prompt"
                />
            </div>

            <div className="flex gap-2 flex-wrap">
                <LemonButton
                    type="primary"
                    icon={<IconRefresh />}
                    onClick={submitPrompt}
                    loading={generatedVegaLiteResponseLoading}
                    disabledReason={!hasColumns ? 'Run a query first' : undefined}
                >
                    Regenerate
                </LemonButton>
                <LemonButton
                    type="secondary"
                    icon={<IconRevert />}
                    onClick={() => updatePrompt(DEFAULT_GENERATED_VEGA_LITE_PROMPT)}
                >
                    Reset prompt
                </LemonButton>
                <LemonButton
                    type="secondary"
                    icon={<IconCopy />}
                    disabledReason={!specForJson ? 'No JSON to copy' : undefined}
                    onClick={() => void copyToClipboard(JSON.stringify(specForJson, null, 2), 'Vega-Lite JSON')}
                >
                    Copy JSON
                </LemonButton>
            </div>

            <LemonSwitch label="Show JSON" checked={showJson} onChange={setShowJson} />

            {showJson ? (
                <div className="flex flex-col gap-2">
                    {generatedSettings.warnings?.length ? (
                        <LemonBanner type="info">
                            <ul className="list-disc pl-4">
                                {generatedSettings.warnings.map((warning, index) => (
                                    <li key={`${warning}-${index}`}>{warning}</li>
                                ))}
                            </ul>
                        </LemonBanner>
                    ) : null}
                    {specForJson ? (
                        <div className="border rounded bg-surface-primary p-2 overflow-auto">
                            <JSONViewer src={specForJson as object} name={null} collapsed={1} sortKeys />
                        </div>
                    ) : null}
                </div>
            ) : null}
        </div>
    )
}
