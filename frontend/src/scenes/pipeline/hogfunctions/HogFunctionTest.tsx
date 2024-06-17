import { TZLabel } from '@posthog/apps-common'
import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSwitch, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CodeEditorResizeable } from 'lib/components/CodeEditors'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { Query } from '~/queries/Query/Query'

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
            height={300}
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
            }}
        />
    )
}

export function HogFunctionTest(props: HogFunctionTestLogicProps): JSX.Element {
    const { testEvent, testInvocation, isTestInvocationSubmitting, matchingEventsQuery, testResult } = useValues(
        hogFunctionTestLogic(props)
    )
    const { submitTestInvocation, setTestEvent, setTestResult } = useActions(hogFunctionTestLogic(props))

    return (
        <div>
            <Form logic={hogFunctionTestLogic} props={props} formKey="testInvocation" enableFormOnSubmit>
                <div className="border bg-bg-light rounded p-3 space-y-2">
                    <div className="flex items-center gap-2 justify-end">
                        <h2 className="flex-1 m-0">Testing</h2>

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
                                                            actually be called but instead will be mocked out with the
                                                            fetch content logged instead
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
                    </div>

                    {testResult ? (
                        <div className="space-y-2">
                            <LemonLabel>Test invocation context</LemonLabel>
                            <HogFunctionTestEditor value={testInvocation.globals} />
                            <LemonLabel>
                                <div className="flex flex-1 justify-between gap-2">
                                    Test invocation result{' '}
                                    <LemonTag type={testResult.status === 'success' ? 'success' : 'danger'}>
                                        {testResult.status}
                                    </LemonTag>
                                </div>
                            </LemonLabel>

                            <LemonTable
                                dataSource={testResult.logs ?? []}
                                columns={[
                                    {
                                        title: 'Timestamp',
                                        key: 'timestamp',
                                        dataIndex: 'timestamp',
                                        render: (timestamp) => <TZLabel time={timestamp} />,
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
                    ) : testEvent === null ? (
                        <div>
                            <LemonLabel>Select a matching event to test with</LemonLabel>
                            <p>Select an event to test your function with. You can edit it after selecting</p>

                            <div className="flex flex-col border rounded overflow-y-auto max-h-120">
                                {matchingEventsQuery ? <Query query={matchingEventsQuery} /> : null}
                            </div>

                            <LemonButton onClick={() => {}}>Test event</LemonButton>
                        </div>
                    ) : (
                        <div className="space-y-2">
                            <LemonField name="globals" label="Test invocation context">
                                {({ value, onChange }) => (
                                    <>
                                        <div className="flex items-start justify-end">
                                            <p className="flex-1">
                                                The globals object is the context in which your function will be tested.
                                                It should contain all the data that your function will need to run
                                            </p>
                                            <LemonButton type="secondary" onClick={() => setTestEvent(null)}>
                                                Choose different event
                                            </LemonButton>
                                        </div>

                                        <HogFunctionTestEditor value={value} onChange={onChange} />
                                    </>
                                )}
                            </LemonField>
                        </div>
                    )}
                </div>
            </Form>
        </div>
    )
}
