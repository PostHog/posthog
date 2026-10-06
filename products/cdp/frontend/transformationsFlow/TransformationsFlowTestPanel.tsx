import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonLabel } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { transformationsFlowLogic } from './transformationsFlowLogic'
import { TestStepOutcome, getStepText } from './transformationsFlowUtils'

const OUTCOME_DESCRIPTIONS: Record<TestStepOutcome, string> = {
    changed: 'This transformation changed the event.',
    unchanged: 'This transformation ran and did not change the event.',
    skipped: 'The event does not match the filters of this transformation, so it did not run.',
    dropped: 'This step dropped the event. PostHog does not store it, and the later steps do not run.',
    error: 'This transformation failed. Ingestion sends the event to the next step without changes.',
    passed: 'The test does not simulate this step. The event goes to the next step without changes.',
    kept: 'The event does not match the event filter, or the filter is off. The event goes to the next step.',
    counted:
        'The event matches the event filter. The filter is in dry run, so PostHog only counts the event. The event goes to the next step.',
}

const READ_ONLY_EDITOR_OPTIONS = {
    readOnly: true,
    lineNumbers: 'off' as const,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
}

export function TransformationsFlowTestPanel(): JSX.Element {
    const {
        testEventInput,
        testEvent,
        testProgress,
        testRunning,
        testFinished,
        testDroppedBy,
        testResults,
        testSteps,
        selectedStep,
        currentTestEvent,
    } = useValues(transformationsFlowLogic)
    const { setTestEventInput, runNextTestStep, runAllTestSteps, resetTest } = useActions(transformationsFlowLogic)

    const testStarted = testProgress > 0
    const selectedIndex = selectedStep ? testSteps.findIndex((step) => step.id === selectedStep.id) : -1
    const selectedVisited = selectedIndex !== -1 && selectedIndex < testProgress
    const selectedResult = selectedStep ? testResults[selectedStep.id] : undefined
    const runDisabledReason = !testEvent
        ? 'Fix the test event first'
        : testFinished
          ? 'The test is complete. Reset it to run again.'
          : undefined

    return (
        <div className="flex flex-col gap-3">
            <p className="m-0">
                Send an example event through your steps, one at a time. The test uses your saved event filter and
                transformations, and it does not store any events.
            </p>

            <div className="flex flex-col gap-1">
                <LemonLabel>Test event</LemonLabel>
                <CodeEditorResizeable
                    language="json"
                    value={testEventInput}
                    onChange={(value) => setTestEventInput(value ?? '')}
                    height={240}
                    options={{
                        readOnly: testStarted,
                        lineNumbers: 'off',
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                    }}
                />
                {!testEvent && (
                    <LemonBanner type="error">
                        The test event must be valid JSON with an "event" name. Fix it to run the test.
                    </LemonBanner>
                )}
                {testStarted && <span className="text-xs text-secondary">Reset the test to edit the event.</span>}
            </div>

            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={testRunning}
                    disabledReason={runDisabledReason}
                    onClick={runNextTestStep}
                    data-attr="transformations-flow-test-next"
                >
                    {testStarted ? 'Run next step' : 'Start test'}
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason={testRunning ? 'The test is running' : runDisabledReason}
                    onClick={runAllTestSteps}
                    data-attr="transformations-flow-test-all"
                >
                    Run all steps
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    disabledReason={
                        !testStarted ? 'The test has not started' : testRunning ? 'The test is running' : undefined
                    }
                    onClick={resetTest}
                    data-attr="transformations-flow-test-reset"
                >
                    Reset
                </LemonButton>
            </div>

            {testDroppedBy ? (
                <LemonBanner type="warning">
                    {getStepText(testDroppedBy).title} dropped the event. PostHog does not store it.
                </LemonBanner>
            ) : testFinished ? (
                <LemonBanner type="success">The event went through all the steps.</LemonBanner>
            ) : null}

            {selectedStep && selectedVisited && (
                <div className="flex flex-col gap-2">
                    <LemonLabel>Result of this step</LemonLabel>
                    <p className="m-0">{OUTCOME_DESCRIPTIONS[selectedResult?.outcome ?? 'passed']}</p>
                    {selectedResult?.errors.map((error, index) => (
                        <LemonBanner key={index} type="error">
                            {error}
                        </LemonBanner>
                    ))}
                    {selectedResult?.outcome === 'changed' && selectedResult.output && (
                        <>
                            <span className="text-xs text-secondary">
                                The left side shows the event before this step. The right side shows the event after it.
                            </span>
                            <CodeEditorResizeable
                                language="json"
                                originalValue={JSON.stringify(selectedResult.input, null, 2)}
                                value={JSON.stringify(selectedResult.output, null, 2)}
                                height={320}
                                options={READ_ONLY_EDITOR_OPTIONS}
                            />
                        </>
                    )}
                </div>
            )}

            {testFinished && !testDroppedBy && currentTestEvent && (
                <div className="flex flex-col gap-1">
                    <LemonLabel>Event that PostHog stores</LemonLabel>
                    <CodeEditorResizeable
                        language="json"
                        value={JSON.stringify(currentTestEvent, null, 2)}
                        height={320}
                        options={READ_ONLY_EDITOR_OPTIONS}
                    />
                </div>
            )}
        </div>
    )
}
