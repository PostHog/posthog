import { IconInfo, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonLabel, LemonSwitch, LemonTable, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { useRef } from 'react'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { hogFunctionSourceWebhookTestLogic } from './hogFunctionSourceWebhookTestLogic'

export function HogFunctionSourceWebhookTest(): JSX.Element {
    const { logicProps } = useValues(hogFunctionConfigurationLogic)
    const { isTestInvocationSubmitting, testResult, expanded, testInvocation } = useValues(
        hogFunctionSourceWebhookTestLogic(logicProps)
    )
    const { submitTestInvocation, setTestResult, toggleExpanded } = useActions(
        hogFunctionSourceWebhookTestLogic(logicProps)
    )

    const testResultsRef = useRef<HTMLDivElement>(null)

    const inactive = !expanded

    return (
        <Form logic={hogFunctionSourceWebhookTestLogic} props={logicProps} formKey="testInvocation" enableFormOnSubmit>
            <div
                ref={testResultsRef}
                className={clsx(
                    'p-3 rounded border',
                    expanded ? 'bg-surface-primary' : 'bg-surface-secondary',
                    expanded ? 'min-h-120' : ''
                )}
            >
                <div className="flex gap-2 justify-end items-center mb-2">
                    <div className="flex-1 deprecated-space-y-2">
                        <h2 className="flex gap-2 items-center mb-0">
                            <span>Testing</span>
                        </h2>
                        {inactive ? <p>Click here to test your webhook</p> : null}
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
                                    <LemonField name="mock_request">
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
                                                                When disabled, the webhook request will be sent but only
                                                                tested without creating events or performing HTTP
                                                                requests.
                                                            </>
                                                        }
                                                    >
                                                        <span className="flex gap-2">
                                                            Debug webhook request only
                                                            <IconInfo className="text-lg" />
                                                        </span>
                                                    </Tooltip>
                                                }
                                            />
                                        )}
                                    </LemonField>
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
                                    {testResult.status === 'success' ? 'Success' : 'Error'}
                                </LemonBanner>

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
                                <LemonField name="headers" label="HTTP Headers">
                                    {({ value, onChange }) => (
                                        <>
                                            <div className="deprecated-space-y-2">
                                                <div />
                                            </div>
                                            <CodeEditorResizeable language="json" value={value} onChange={onChange} />
                                        </>
                                    )}
                                </LemonField>
                                <LemonField name="body" label="HTTP Body">
                                    {({ value, onChange }) => (
                                        <CodeEditorResizeable language="json" value={value} onChange={onChange} />
                                    )}
                                </LemonField>
                            </div>
                        )}

                        <LemonDivider className="my-4" />

                        <h2>Example request</h2>

                        <p>Below is an example of how to test the webhook using curl.</p>

                        {/* Show an example curl request */}
                        <CodeSnippet thing="Example request">
                            {`curl -X POST -H "Content-Type: application/json" \\
  -d '${testInvocation.body}' \\
  ${window.location.origin}/public/webhooks/${logicProps.id}`}
                        </CodeSnippet>
                    </>
                ) : null}
            </div>
        </Form>
    )
}
