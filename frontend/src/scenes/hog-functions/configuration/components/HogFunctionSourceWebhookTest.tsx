import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useRef } from 'react'

import { IconInfo, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { hogFunctionSourceWebhookTestLogic } from './hogFunctionSourceWebhookTestLogic'

export function HogFunctionSourceWebhookTest(): JSX.Element {
    const { logicProps, configurationChanged } = useValues(hogFunctionConfigurationLogic)
    const { isTestInvocationSubmitting, testResult, expanded, exampleCurlRequest, testInvocation } = useValues(
        hogFunctionSourceWebhookTestLogic(logicProps)
    )
    const { submitTestInvocation, setTestResult, toggleExpanded } = useActions(
        hogFunctionSourceWebhookTestLogic(logicProps)
    )

    const testResultsRef = useRef<HTMLDivElement>(null)

    const unsaved = !logicProps.id

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
                        {!expanded ? (
                            unsaved ? (
                                <p>Testing tools are only available after creating the webhook</p>
                            ) : (
                                <p>Click here to test your webhook</p>
                            )
                        ) : null}
                    </div>

                    {!expanded ? (
                        <LemonButton
                            data-attr="expand-hog-testing"
                            type="secondary"
                            disabledReason={
                                unsaved ? 'Testing tools are only available after creating the webhook' : undefined
                            }
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
                                                        When disabled, the webhook request will be sent but only tested
                                                        without creating events or performing HTTP requests.
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
                        <LemonBanner type={configurationChanged ? 'warning' : 'info'} className="mb-2">
                            {configurationChanged ? <span>You have unsaved changes.</span> : null}
                            <span>
                                Testing is performed against the latest saved configuration and will create real events.
                            </span>
                        </LemonBanner>

                        <div className="flex flex-col gap-2">
                            <LemonField name="method" label="HTTP method">
                                <LemonSelect
                                    options={[
                                        { label: 'POST', value: 'POST' },
                                        { label: 'GET', value: 'GET' },
                                    ]}
                                />
                            </LemonField>

                            <LemonField name="query" label="HTTP Query Parameters">
                                <LemonInput placeholder="e.g. ph_event=event&ph_distinct_id=my-distinct-id" />
                            </LemonField>
                            <LemonField name="headers" label="HTTP Headers">
                                {({ value, onChange }) => (
                                    <CodeEditorResizeable
                                        language="json"
                                        value={value}
                                        onChange={onChange}
                                        maxHeight={200}
                                    />
                                )}
                            </LemonField>
                            {testInvocation.method !== 'GET' && (
                                <LemonField name="body" label="HTTP Body">
                                    {({ value, onChange }) => (
                                        <CodeEditorResizeable
                                            language="json"
                                            value={value}
                                            onChange={onChange}
                                            maxHeight={200}
                                        />
                                    )}
                                </LemonField>
                            )}
                            <LemonDivider className="my-4" />
                            <div className="flex flex-col gap-2">
                                <div className="flex gap-2 justify-between items-center">
                                    <LemonLabel className="flex-1">
                                        Response
                                        {testResult && (
                                            <>
                                                <LemonTag
                                                    type={
                                                        testResult.status >= 200 && testResult.status < 300
                                                            ? 'success'
                                                            : 'danger'
                                                    }
                                                >
                                                    {testResult.status}
                                                </LemonTag>
                                            </>
                                        )}
                                    </LemonLabel>
                                    {testResult ? (
                                        <LemonButton type="secondary" size="small" onClick={() => setTestResult(null)}>
                                            Clear
                                        </LemonButton>
                                    ) : null}
                                    <LemonButton
                                        type="primary"
                                        data-attr="test-hog-webhook"
                                        onClick={submitTestInvocation}
                                        loading={isTestInvocationSubmitting}
                                        size="small"
                                    >
                                        Test webhook
                                    </LemonButton>
                                </div>

                                {testResult ? (
                                    <div className="flex flex-col gap-2">
                                        <CodeSnippet thing="Response body">{testResult.body}</CodeSnippet>
                                    </div>
                                ) : isTestInvocationSubmitting ? (
                                    <LemonSkeleton className="h-12" />
                                ) : (
                                    <p>No response yet</p>
                                )}
                            </div>
                        </div>

                        <LemonDivider className="my-4" />

                        {/* Show an example curl request */}
                        <CodeSnippet thing="Example request">{exampleCurlRequest}</CodeSnippet>
                    </>
                ) : null}
            </div>
        </Form>
    )
}
