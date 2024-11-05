import { TZLabel } from '@posthog/apps-common'
import { IconInfo, IconX } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSwitch, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { hogFunctionTestLogic, HogFunctionTestLogicProps } from './hogFunctionTestLogic'

const HogFunctionTestEditor = ({
    value,
    onChange,
}: {
    value: string
    onChange?: (value?: string) => void
}): JSX.Element => {
    return (
        <CodeEditorResizeable
            language="json"
            value={value}
            height={400}
            onChange={onChange}
            options={{
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
    )
}

export function HogFunctionTestPlaceholder({
    title,
    description,
}: {
    title?: string | JSX.Element
    description?: string | JSX.Element
}): JSX.Element {
    return (
        <div className="border bg-accent-3000 rounded p-3 space-y-2">
            <h2 className="flex-1 m-0">{title || 'Testing'}</h2>
            <p>{description || 'Save your configuration to enable testing'}</p>
        </div>
    )
}

export function HogFunctionTest(props: HogFunctionTestLogicProps): JSX.Element {
    const { isTestInvocationSubmitting, testResult, expanded, sampleGlobalsLoading, sampleGlobalsError, type } =
        useValues(hogFunctionTestLogic(props))
    const { submitTestInvocation, setTestResult, toggleExpanded, loadSampleGlobals } = useActions(
        hogFunctionTestLogic(props)
    )

    return (
        <Form logic={hogFunctionTestLogic} props={props} formKey="testInvocation" enableFormOnSubmit>
            <div
                className={clsx('border rounded p-3 space-y-2', expanded ? 'bg-bg-light min-h-120' : 'bg-accent-3000')}
            >
                <div className="flex items-center gap-2 justify-end">
                    <div className="flex-1 space-y-2">
                        <h2 className="mb-0">Testing</h2>
                        {!expanded &&
                            (type === 'email' ? (
                                <p>Click here to test the provider with a sample e-mail</p>
                            ) : type === 'broadcast' ? (
                                <p>Click here to test your broadcast</p>
                            ) : (
                                <p>Click here to test your function with an example event</p>
                            ))}
                    </div>

                    {!expanded ? (
                        <LemonButton type="secondary" onClick={() => toggleExpanded()}>
                            Start testing
                        </LemonButton>
                    ) : (
                        <>
                            {testResult ? (
                                <LemonButton
                                    type="primary"
                                    onClick={() => setTestResult(null)}
                                    loading={isTestInvocationSubmitting}
                                >
                                    Clear test result
                                </LemonButton>
                            ) : (
                                <>
                                    {type === 'destination' ? (
                                        <LemonButton
                                            type="secondary"
                                            onClick={loadSampleGlobals}
                                            loading={sampleGlobalsLoading}
                                            tooltip="Find the last event matching filters, and use it to populate the globals below."
                                        >
                                            Refresh globals
                                        </LemonButton>
                                    ) : null}
                                    <LemonField name="mock_async_functions">
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                bordered
                                                onChange={onChange}
                                                checked={value}
                                                label={
                                                    <Tooltip
                                                        title={
                                                            <>
                                                                When selected, async functions such as `fetch` will not
                                                                actually be called but instead will be mocked out with
                                                                the fetch content logged instead
                                                            </>
                                                        }
                                                    >
                                                        <span className="flex gap-2">
                                                            Mock out async functions
                                                            <IconInfo className="text-lg" />
                                                        </span>
                                                    </Tooltip>
                                                }
                                            />
                                        )}
                                    </LemonField>
                                    <LemonButton
                                        type="primary"
                                        onClick={submitTestInvocation}
                                        loading={isTestInvocationSubmitting}
                                    >
                                        Test function
                                    </LemonButton>
                                </>
                            )}

                            <LemonButton icon={<IconX />} onClick={() => toggleExpanded()} tooltip="Hide testing" />
                        </>
                    )}
                </div>

                {expanded && (
                    <>
                        {testResult ? (
                            <div className="space-y-2">
                                <div className="flex justify-between items-center">
                                    <LemonLabel>Test invocation result </LemonLabel>
                                    <LemonTag type={testResult.status === 'success' ? 'success' : 'danger'}>
                                        {testResult.status}
                                    </LemonTag>
                                </div>

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
                            <div className="space-y-2">
                                <LemonField name="globals">
                                    {({ value, onChange }) => (
                                        <>
                                            <div className="space-y-2">
                                                <div>
                                                    {type === 'broadcast'
                                                        ? 'The test broadcast will be sent with this sample data:'
                                                        : type === 'email'
                                                        ? 'The provider will be tested with this sample data:'
                                                        : 'Here are all the global variables you can use in your code:'}
                                                </div>
                                                {sampleGlobalsError ? (
                                                    <div className="text-warning">{sampleGlobalsError}</div>
                                                ) : null}
                                            </div>
                                            <HogFunctionTestEditor value={value} onChange={onChange} />
                                        </>
                                    )}
                                </LemonField>
                            </div>
                        )}
                    </>
                )}
            </div>
        </Form>
    )
}
