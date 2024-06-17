import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSwitch, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CodeEditorResizeable } from 'lib/components/CodeEditors'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { Query } from '~/queries/Query/Query'

import { hogFunctionTestLogic, HogFunctionTestLogicProps } from './hogFunctionTestLogic'

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
                        <div>
                            <LemonLabel>Test invocation context</LemonLabel>
                            <CodeEditorResizeable
                                language="json"
                                value={testInvocation.globals}
                                height={300}
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
                            <LemonLabel>Test invocation result</LemonLabel>
                            <p>Result!: {JSON.stringify(testResult)}</p>
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
