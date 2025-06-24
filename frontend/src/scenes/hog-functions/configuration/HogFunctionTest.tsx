import { IconInfo, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonLabel,
    LemonSegmentedButton,
    LemonSwitch,
    LemonTable,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { editor as monacoEditor, MarkerSeverity } from 'monaco-editor'
import { useRef } from 'react'

import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'
import { hogFunctionTestLogic } from './hogFunctionTestLogic'

export function HogFunctionTestPlaceholder({
    title,
    description,
}: {
    title?: string | JSX.Element
    description?: string | JSX.Element
}): JSX.Element {
    return (
        <div className="p-3 space-y-2 rounded border bg-accent-3000">
            <h2 className="flex-1 m-0">{title || 'Testing'}</h2>
            <p>{description || 'Save your configuration to enable testing'}</p>
        </div>
    )
}

const HogFunctionTestEditor = ({
    value,
    onChange,
    readOnly = false,
}: {
    value: string
    onChange?: (value?: string) => void
    readOnly?: boolean
}): JSX.Element => {
    const editorRef = useRef<monacoEditor.IStandaloneCodeEditor | null>(null)
    const decorationsRef = useRef<string[]>([]) // Track decoration IDs

    const handleValidation = (newValue: string): void => {
        if (!editorRef.current?.getModel()) {
            return
        }
        const model = editorRef.current.getModel()!

        // First clear everything
        monacoEditor.setModelMarkers(model, 'owner', [])

        // Clear existing decorations and get new empty array of IDs
        decorationsRef.current = editorRef.current.deltaDecorations(decorationsRef.current, [])

        // Now validate with clean state
        try {
            JSON.parse(newValue)
            // Valid JSON - keep decorations cleared
        } catch (err: any) {
            // Invalid JSON - add new decoration
            const match = err.message.match(/position (\d+)/)
            if (match) {
                const position = parseInt(match[1], 10)
                const pos = model.getPositionAt(position)

                // Set error marker
                monacoEditor.setModelMarkers(model, 'owner', [
                    {
                        startLineNumber: pos.lineNumber,
                        startColumn: pos.column,
                        endLineNumber: pos.lineNumber,
                        endColumn: pos.column + 1,
                        message: err.message,
                        severity: MarkerSeverity.Error,
                    },
                ])

                // Set new decoration and store the IDs
                decorationsRef.current = editorRef.current.deltaDecorations(decorationsRef.current, [
                    {
                        range: {
                            startLineNumber: pos.lineNumber,
                            startColumn: 1,
                            endLineNumber: pos.lineNumber,
                            endColumn: model.getLineLength(pos.lineNumber) + 1,
                        },
                        options: {
                            isWholeLine: true,
                            className: 'bg-danger-highlight',
                            glyphMarginClassName: 'text-danger flex items-center justify-center',
                            glyphMarginHoverMessage: { value: err.message },
                        },
                    },
                ])

                // Scroll to error
                editorRef.current.revealLineInCenter(pos.lineNumber)
            }
        }
    }

    return (
        <CodeEditorResizeable
            language="json"
            value={value}
            height={400}
            onChange={(newValue) => {
                if (!readOnly) {
                    onChange?.(newValue)
                    handleValidation(newValue ?? '')
                }
            }}
            onMount={(editor) => {
                editorRef.current = editor
                handleValidation(value)
            }}
            options={{
                lineNumbers: 'on',
                minimap: {
                    enabled: false,
                },
                quickSuggestions: {
                    other: true,
                    strings: true,
                },
                suggest: {
                    showWords: false,
                    showFields: false,
                    showKeywords: false,
                },
                scrollbar: {
                    vertical: 'auto',
                    verticalScrollbarSize: 14,
                },
                folding: true,
                glyphMargin: true,
                readOnly: readOnly,
            }}
        />
    )
}

export function HogFunctionTest(): JSX.Element {
    const { logicProps, canLoadSampleGlobals } = useValues(hogFunctionConfigurationLogic)
    const {
        isTestInvocationSubmitting,
        testResult,
        expanded,
        sampleGlobalsLoadingAndNotCancelled,
        sampleGlobalsError,
        type,
        savedGlobals,
        testInvocation,
        testResultMode,
        sortedTestsResult,
        jsonError,
    } = useValues(hogFunctionTestLogic(logicProps))
    const {
        submitTestInvocation,
        setTestResult,
        toggleExpanded,
        loadSampleGlobals,
        deleteSavedGlobals,
        setSampleGlobals,
        saveGlobals,
        setTestResultMode,
        cancelSampleGlobalsLoading,
    } = useActions(hogFunctionTestLogic(logicProps))

    const testResultsRef = useRef<HTMLDivElement>(null)
    const inactive = !expanded

    return (
        <Form logic={hogFunctionTestLogic} props={logicProps} formKey="testInvocation" enableFormOnSubmit>
            <div
                ref={testResultsRef}
                className={clsx(
                    'p-3 rounded border deprecated-space-y-2',
                    expanded ? 'bg-surface-primary' : 'bg-surface-secondary',
                    expanded ? 'min-h-120' : ''
                )}
            >
                <div className="flex gap-2 justify-end items-center">
                    <div className="flex-1 deprecated-space-y-2">
                        <h2 className="flex gap-2 items-center mb-0">
                            <span>Testing</span>
                        </h2>
                        {inactive ? <p>Click here to test your function with an example event</p> : null}
                    </div>

                    {inactive ? (
                        <LemonButton
                            data-attr="expand-hog-testing"
                            type="secondary"
                            onClick={() => {
                                toggleExpanded()
                                // Add a small delay to allow the content to expand
                                setTimeout(() => {
                                    testResultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                                }, 100)
                            }}
                        >
                            Start testing
                        </LemonButton>
                    ) : (
                        <>
                            {testResult ? (
                                <LemonButton
                                    type="primary"
                                    onClick={() => setTestResult(null)}
                                    loading={isTestInvocationSubmitting}
                                    data-attr="clear-hog-test-result"
                                >
                                    Clear test result
                                </LemonButton>
                            ) : (
                                <>
                                    <More
                                        dropdown={{ closeOnClickInside: false }}
                                        overlay={
                                            <>
                                                <LemonField name="mock_async_functions">
                                                    {({ value, onChange }) => (
                                                        <LemonSwitch
                                                            onChange={(v) => onChange(!v)}
                                                            checked={!value}
                                                            data-attr="toggle-hog-test-mocking"
                                                            className="px-2 py-1"
                                                            label={
                                                                <Tooltip
                                                                    title={
                                                                        <>
                                                                            When disabled, async functions such as
                                                                            `fetch` will not be called. Instead they
                                                                            will be mocked out and logged.
                                                                        </>
                                                                    }
                                                                >
                                                                    <span className="flex gap-2">
                                                                        Make real HTTP requests
                                                                        <IconInfo className="text-lg" />
                                                                    </span>
                                                                </Tooltip>
                                                            }
                                                        />
                                                    )}
                                                </LemonField>
                                                <LemonDivider />
                                                {savedGlobals.map(({ name, globals }, index) => (
                                                    <div className="flex justify-between w-full" key={index}>
                                                        <LemonButton
                                                            data-attr="open-hog-test-data"
                                                            key={index}
                                                            onClick={() => setSampleGlobals(globals)}
                                                            fullWidth
                                                            className="flex-1"
                                                        >
                                                            {name}
                                                        </LemonButton>
                                                        <LemonButton
                                                            data-attr="delete-hog-test-data"
                                                            size="small"
                                                            icon={<IconX />}
                                                            onClick={() => deleteSavedGlobals(index)}
                                                            tooltip="Delete saved test data"
                                                        />
                                                    </div>
                                                ))}
                                                {testInvocation.globals && (
                                                    <LemonButton
                                                        fullWidth
                                                        data-attr="save-hog-test-data"
                                                        onClick={() => {
                                                            const name = prompt('Name this test data')
                                                            if (name) {
                                                                saveGlobals(name, JSON.parse(testInvocation.globals))
                                                            }
                                                        }}
                                                        disabledReason={(() => {
                                                            try {
                                                                JSON.parse(testInvocation.globals)
                                                            } catch {
                                                                return 'Invalid globals JSON'
                                                            }
                                                            return undefined
                                                        })()}
                                                    >
                                                        Save test data
                                                    </LemonButton>
                                                )}
                                            </>
                                        }
                                    />
                                    {canLoadSampleGlobals ? (
                                        <LemonButton
                                            type="secondary"
                                            onClick={() => {
                                                if (sampleGlobalsLoadingAndNotCancelled) {
                                                    cancelSampleGlobalsLoading()
                                                } else {
                                                    loadSampleGlobals()
                                                }
                                            }}
                                            tooltip="Find the last event matching filters, and use it to populate the globals below."
                                            icon={sampleGlobalsLoadingAndNotCancelled ? <Spinner /> : undefined}
                                        >
                                            {sampleGlobalsLoadingAndNotCancelled ? 'Cancel loading' : 'Load new event'}
                                        </LemonButton>
                                    ) : null}
                                    <LemonButton
                                        type="primary"
                                        data-attr="test-hog-function"
                                        onClick={submitTestInvocation}
                                        loading={isTestInvocationSubmitting}
                                    >
                                        Test function
                                    </LemonButton>
                                </>
                            )}

                            {expanded && (
                                <LemonButton
                                    data-attr="hide-hog-testing"
                                    icon={<IconX />}
                                    onClick={() => toggleExpanded()}
                                    tooltip="Hide testing"
                                />
                            )}
                        </>
                    )}
                </div>

                {expanded ? (
                    <>
                        {testResult ? (
                            <div className="deprecated-space-y-2" data-attr="test-results">
                                <LemonBanner
                                    type={
                                        testResult.status === 'success'
                                            ? 'success'
                                            : testResult.status === 'skipped'
                                            ? 'warning'
                                            : 'error'
                                    }
                                >
                                    {testResult.status === 'success'
                                        ? 'Success'
                                        : testResult.status === 'skipped'
                                        ? `${
                                              type.charAt(0).toUpperCase() + type.slice(1)
                                          } was skipped because the event did not match the filter criteria`
                                        : 'Error'}
                                </LemonBanner>

                                {type === 'transformation' && testResult.status !== 'error' ? (
                                    <>
                                        <div className="flex gap-2 justify-between items-center">
                                            <LemonLabel>Transformation result</LemonLabel>

                                            {sortedTestsResult?.hasDiff && (
                                                <LemonSegmentedButton
                                                    size="xsmall"
                                                    options={[
                                                        { value: 'raw', label: 'Output' },
                                                        { value: 'diff', label: 'Diff' },
                                                    ]}
                                                    onChange={(value) => setTestResultMode(value as 'raw' | 'diff')}
                                                    value={testResultMode}
                                                />
                                            )}
                                        </div>
                                        <p>Below you can see the event after the transformation has been applied.</p>
                                        {testResult.result ? (
                                            <>
                                                {!sortedTestsResult?.hasDiff && (
                                                    <LemonBanner type="info">
                                                        {testResult.status === 'skipped'
                                                            ? 'The event was not modified as it did not match the filter criteria.'
                                                            : 'The event was unmodified by the transformation.'}
                                                    </LemonBanner>
                                                )}
                                                <CodeEditorResizeable
                                                    language="json"
                                                    originalValue={
                                                        sortedTestsResult?.hasDiff && testResultMode === 'diff'
                                                            ? sortedTestsResult?.input
                                                            : undefined
                                                    }
                                                    value={sortedTestsResult?.output}
                                                    height={400}
                                                    options={{
                                                        readOnly: true,
                                                        lineNumbers: 'off',
                                                        minimap: {
                                                            enabled: false,
                                                        },
                                                        quickSuggestions: {
                                                            other: true,
                                                            strings: true,
                                                        },
                                                        suggest: {
                                                            showWords: false,
                                                            showFields: false,
                                                            showKeywords: false,
                                                        },
                                                        scrollbar: {
                                                            vertical: 'hidden',
                                                            verticalScrollbarSize: 0,
                                                        },
                                                        folding: true,
                                                    }}
                                                />
                                            </>
                                        ) : (
                                            <LemonBanner type="warning">
                                                The event was dropped by the transformation. If this is expected then
                                                great news! If not, you should double check the configuration.
                                            </LemonBanner>
                                        )}
                                    </>
                                ) : null}

                                <LemonLabel>Test invocation logs</LemonLabel>

                                <LemonTable
                                    dataSource={testResult.logs ?? []}
                                    columns={[
                                        {
                                            title: 'Timestamp',
                                            key: 'timestamp',
                                            dataIndex: 'timestamp',
                                            render: (timestamp) => <TZLabel time={timestamp as string} />,
                                            width: 0,
                                        },
                                        {
                                            width: 100,
                                            title: 'Level',
                                            key: 'level',
                                            dataIndex: 'level',
                                        },
                                        {
                                            title: 'Message',
                                            key: 'message',
                                            dataIndex: 'message',
                                            render: (message) => <code className="whitespace-pre-wrap">{message}</code>,
                                        },
                                    ]}
                                    className="ph-no-capture"
                                    rowKey="timestamp"
                                    pagination={{ pageSize: 200, hideOnSinglePage: true }}
                                />
                            </div>
                        ) : (
                            <div className="deprecated-space-y-2">
                                <LemonField name="globals">
                                    {({ value, onChange }) => (
                                        <>
                                            <div className="deprecated-space-y-2">
                                                <div>Here are all the global variables you can use in your code:</div>
                                                {sampleGlobalsError ? (
                                                    <div className="text-warning">{sampleGlobalsError}</div>
                                                ) : null}
                                            </div>
                                            <HogFunctionTestEditor
                                                value={value}
                                                onChange={onChange}
                                                readOnly={sampleGlobalsLoadingAndNotCancelled}
                                            />
                                        </>
                                    )}
                                </LemonField>
                            </div>
                        )}
                    </>
                ) : null}
            </div>

            {jsonError && <LemonBanner type="error">JSON Error: {jsonError}</LemonBanner>}
        </Form>
    )
}
