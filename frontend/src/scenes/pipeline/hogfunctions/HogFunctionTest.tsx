import { TZLabel } from '@posthog/apps-common'
import { IconInfo, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonLabel,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'
import { LemonField } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { More } from 'lib/lemon-ui/LemonButton/More'
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
    const {
        isTestInvocationSubmitting,
        testResult,
        expanded,
        sampleGlobalsLoading,
        sampleGlobalsError,
        type,
        savedGlobals,
        testInvocation,
    } = useValues(hogFunctionTestLogic(props))
    const {
        submitTestInvocation,
        setTestResult,
        toggleExpanded,
        loadSampleGlobals,
        deleteSavedGlobals,
        setSampleGlobals,
        saveGlobals,
    } = useActions(hogFunctionTestLogic(props))

    return (
        <Form logic={hogFunctionTestLogic} props={props} formKey="testInvocation" enableFormOnSubmit>
            <div
                className={clsx('border rounded p-3 space-y-2', expanded ? 'bg-bg-light min-h-120' : 'bg-accent-3000')}
            >
                <div className="flex items-center gap-2 justify-end">
                    <div className="flex-1 space-y-2">
                        <h2 className="mb-0 flex gap-2 items-center">
                            <span>Testing</span>
                            {sampleGlobalsLoading ? <Spinner /> : null}
                        </h2>
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
                        <LemonButton data-attr="expand-hog-testing" type="secondary" onClick={() => toggleExpanded()}>
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
                                                <LemonButton
                                                    fullWidth
                                                    onClick={loadSampleGlobals}
                                                    loading={sampleGlobalsLoading}
                                                    tooltip="Find the last event matching filters, and use it to populate the globals below."
                                                >
                                                    Fetch new event
                                                </LemonButton>
                                                <LemonDivider />
                                                {savedGlobals.map(({ name, globals }, index) => (
                                                    <div className="flex w-full justify-between" key={index}>
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
                                                            } catch (e) {
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

                            <LemonButton
                                data-attr="hide-hog-testing"
                                icon={<IconX />}
                                onClick={() => toggleExpanded()}
                                tooltip="Hide testing"
                            />
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
