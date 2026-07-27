import { useActions, useValues } from 'kea'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonLabel, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { eventFilterLogic, TestCase, TestResult } from './eventFilterLogic'

export function EventFilterTestCases(): JSX.Element {
    const { filterForm, testResults, allTestsPass } = useValues(eventFilterLogic)
    const { addTestCase, removeTestCase, updateTestCase } = useActions(eventFilterLogic)

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <LemonLabel>Test cases</LemonLabel>
                {filterForm.test_cases.length > 0 && (
                    <LemonTag type={allTestsPass ? 'success' : 'danger'}>
                        {allTestsPass
                            ? `All ${filterForm.test_cases.length} tests pass`
                            : `${testResults.filter((r: TestResult) => !r.pass).length} of ${filterForm.test_cases.length} failing`}
                    </LemonTag>
                )}
            </div>
            <p className="text-muted text-sm">
                Add test events to verify your filter. Each test specifies whether the event should be dropped or
                ingested. The filter cannot be enabled until all tests pass.
            </p>

            {filterForm.test_cases.length > 0 && (
                <div className="space-y-2">
                    {filterForm.test_cases.map((tc: TestCase, i: number) => {
                        const result = testResults[i]
                        return (
                            <div
                                key={tc._key}
                                className={`border rounded font-mono text-sm ${
                                    result && !result.pass ? 'border-danger' : ''
                                }`}
                            >
                                <div className="flex items-center justify-between px-3 pt-2">
                                    <div className="flex items-center gap-2">
                                        <LemonSelect
                                            size="xsmall"
                                            options={[
                                                { value: 'drop', label: 'Should drop' },
                                                { value: 'ingest', label: 'Should ingest' },
                                            ]}
                                            value={tc.expected_result}
                                            onChange={(value) =>
                                                updateTestCase(i, {
                                                    expected_result: value as 'drop' | 'ingest',
                                                })
                                            }
                                        />
                                        {result && (
                                            <LemonTag type={result.pass ? 'success' : 'danger'}>
                                                {result.pass ? 'Pass' : `Fail (would ${result.actual})`}
                                            </LemonTag>
                                        )}
                                    </div>
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="xsmall"
                                        status="danger"
                                        aria-label="Remove test case"
                                        onClick={() => removeTestCase(i)}
                                    />
                                </div>
                                <div className="px-3 pb-2 pt-1">
                                    <span className="text-muted">{'{'}</span>
                                    <div className="pl-4 space-y-1">
                                        <div className="flex items-center gap-1">
                                            <span className="text-primary">"event"</span>
                                            <span className="text-muted">:</span>
                                            <LemonInput
                                                size="small"
                                                value={tc.event_name}
                                                onChange={(value) => updateTestCase(i, { event_name: value })}
                                                placeholder="$pageview"
                                                className="flex-1 font-mono"
                                            />
                                        </div>
                                        <div className="flex items-center gap-1">
                                            <span className="text-primary">"distinct_id"</span>
                                            <span className="text-muted">:</span>
                                            <LemonInput
                                                size="small"
                                                value={tc.distinct_id}
                                                onChange={(value) => updateTestCase(i, { distinct_id: value })}
                                                placeholder="user-123"
                                                className="flex-1 font-mono"
                                            />
                                        </div>
                                    </div>
                                    <span className="text-muted">{'}'}</span>
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}

            <LemonButton size="small" type="secondary" icon={<IconPlusSmall />} onClick={() => addTestCase()}>
                Add test case
            </LemonButton>
        </div>
    )
}
