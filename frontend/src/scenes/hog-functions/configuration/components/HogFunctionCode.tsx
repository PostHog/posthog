import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDropdown, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import MaxTool from 'scenes/max/MaxTool'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { HogFunctionTemplateOptions } from './HogFunctionTemplateOptions'

export function HogFunctionCode(): JSX.Element {
    const {
        showSource,
        configuration,
        sampleGlobalsWithInputs,
        templateHasChanged,
        type,
        mightDropEvents,
        oldHogCode,
        newHogCode,
    } = useValues(hogFunctionConfigurationLogic)

    const {
        setShowSource,
        setOldHogCode,
        setNewHogCode,
        clearHogCodeDiff,
        reportAIHogFunctionPrompted,
        reportAIHogFunctionAccepted,
        reportAIHogFunctionRejected,
        reportAIHogFunctionPromptOpen,
    } = useActions(hogFunctionConfigurationLogic)

    const sourceCodeRef = useRef<HTMLDivElement>(null)

    const content = (
        <div
            ref={sourceCodeRef}
            className={clsx(
                'p-3 rounded border deprecated-space-y-2',
                showSource ? 'bg-surface-primary' : 'bg-surface-secondary'
            )}
        >
            <div className="flex gap-2 justify-end items-center">
                <div className="flex-1 deprecated-space-y-2">
                    <h2 className="mb-0">Edit source</h2>
                    {!showSource ? <p>Click here to edit the function's source code</p> : null}
                </div>

                {templateHasChanged ? (
                    <LemonDropdown showArrow overlay={<HogFunctionTemplateOptions />}>
                        <LemonButton type="tertiary" size={showSource ? 'xsmall' : 'small'} icon={<IconInfo />}>
                            Modified code
                        </LemonButton>
                    </LemonDropdown>
                ) : null}

                {!showSource ? (
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            setShowSource(true)
                            setTimeout(() => {
                                sourceCodeRef.current?.scrollIntoView({
                                    behavior: 'smooth',
                                    block: 'start',
                                })
                            }, 100)
                        }}
                    >
                        Edit source code
                    </LemonButton>
                ) : (
                    <LemonButton size="xsmall" type="secondary" onClick={() => setShowSource(false)}>
                        Hide source code
                    </LemonButton>
                )}
            </div>

            {showSource ? (
                <LemonField name="hog">
                    {({ value, onChange }) => (
                        <>
                            {!type.startsWith('site_') ? (
                                <span className="text-xs text-secondary">
                                    This is the underlying Hog code that will run whenever this triggers.{' '}
                                    <Link to="https://posthog.com/docs/hog">See the docs</Link> for more info
                                </span>
                            ) : null}
                            {mightDropEvents && (
                                <LemonBanner type="warning" className="mt-2">
                                    <b>Warning:</b> Returning null or undefined will drop the event. If this is
                                    unintentional, return the event object instead.
                                </LemonBanner>
                            )}
                            {type === 'source_webhook' && (
                                <LemonBanner type="info" className="mt-2">
                                    <b>HTTP requests:</b> Webhook sources can call <code>postHogCapture</code> to ingest
                                    events to PostHog. You can also do HTTP calls with <code>fetch</code>. In this case
                                    however, the request will be queued to a background task, a <code>201 Created</code>{' '}
                                    response will be returned and the event will be ingested asynchronously.
                                </LemonBanner>
                            )}
                            <CodeEditorResizeable
                                language={type.startsWith('site_') ? 'typescript' : 'hog'}
                                value={newHogCode ?? value ?? ''}
                                originalValue={oldHogCode && newHogCode ? oldHogCode : undefined}
                                onChange={(v) => {
                                    // If user manually edits while diff is showing, clear the diff
                                    if (oldHogCode && newHogCode) {
                                        clearHogCodeDiff()
                                    }
                                    onChange(v ?? '')
                                }}
                                globals={sampleGlobalsWithInputs}
                                showDiffActions={!!(oldHogCode && newHogCode)}
                                onAcceptChanges={() => {
                                    if (newHogCode) {
                                        onChange(newHogCode)
                                    }
                                    reportAIHogFunctionAccepted()
                                    clearHogCodeDiff()
                                }}
                                onRejectChanges={() => {
                                    if (oldHogCode) {
                                        onChange(oldHogCode)
                                    }
                                    reportAIHogFunctionRejected()
                                    clearHogCodeDiff()
                                }}
                                options={{
                                    minimap: {
                                        enabled: false,
                                    },
                                    wordWrap: 'on',
                                    scrollBeyondLastLine: false,
                                    automaticLayout: true,
                                    fixedOverflowWidgets: true,
                                    suggest: {
                                        showInlineDetails: true,
                                    },
                                    quickSuggestionsDelay: 300,
                                    readOnly: !!(oldHogCode && newHogCode),
                                }}
                            />
                        </>
                    )}
                </LemonField>
            ) : null}
        </div>
    )

    return (
        <MaxTool
            identifier="create_hog_transformation_function"
            context={{
                current_hog_code: configuration.hog ?? '',
            }}
            callback={(toolOutput: string) => {
                // Store the old value before changing
                setOldHogCode(configuration.hog ?? '')
                // Store the new value from Max Tool
                setNewHogCode(toolOutput)
                // Report that AI was prompted
                reportAIHogFunctionPrompted()
                // Don't immediately update the form - let user accept/reject
            }}
            onMaxOpen={() => {
                reportAIHogFunctionPromptOpen()
            }}
            suggestions={[]}
            introOverride={{
                headline: 'What transformation do you want to create?',
                description: 'Let me help you quickly write the code for your transformation, and tweak it.',
            }}
        >
            {content}
        </MaxTool>
    )
}
