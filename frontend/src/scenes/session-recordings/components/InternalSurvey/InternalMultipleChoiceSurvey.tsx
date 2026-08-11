/**
 * @fileoverview A component that displays an interactive survey within a session recording. It handles survey display, user responses, and submission
 */
import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonTextArea, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { SurveyQuestion, SurveyQuestionType } from '~/types'

import { internalMultipleChoiceSurveyLogic } from './internalMultipleChoiceSurveyLogic'

interface InternalSurveyProps {
    surveyId: string
}

function TooExpensiveHelpMessage(): JSX.Element {
    return (
        <>
            <p>
                There are several ways to reduce costs by recording fewer sessions:
                <ul className="list-disc pl-4 text-secondary">
                    <li>Disable automatic recording and programmatically start and stop recordings</li>
                    <li>
                        Set a feature flag with the conditions that define which users or sessions you want to record.
                    </li>
                    <li>Set a minimum recording duration.</li>
                    <li>Set a sampling rate for recordings.</li>
                    <li>Start recording only after certain events (for example after an error).</li>
                    <li>
                        Start recording only after visiting certain pages (for example to avoid starting for every visit
                        to the home page).
                    </li>
                </ul>
            </p>
            <Link to="https://posthog.com/docs/session-replay/cutting-costs" target="_blank">
                Learn more
            </Link>
        </>
    )
}

function PrivacyHelpMessage(): JSX.Element {
    return (
        <>
            <p>
                PostHog offers a range of controls to limit what data is captured by session recordings. Our privacy
                controls run in the browser or mobile app. So, masked data is never sent over the network to PostHog.
            </p>
            <Link to="https://posthog.com/docs/session-replay/privacy" target="_blank">
                Learn more
            </Link>
        </>
    )
}

function PerformanceHelpMessage(): JSX.Element {
    return (
        <>
            <p>
                Session replay allows you to capture network requests and responses, providing insights into network
                performance and potential issues. This feature can be particularly useful for debugging and optimizing
                your application's network interactions.
            </p>
            <ul className="list-disc pl-4 text-secondary">
                <li>
                    <Link to="https://posthog.com/docs/session-replay/network-performance-recording" target="_blank">
                        Network performance recording
                    </Link>
                </li>
                <li>
                    <Link
                        to="https://posthog.com/docs/session-replay/canvas-recording#canvas-recording-performance"
                        target="_blank"
                    >
                        Canvas recording performance
                    </Link>
                </li>
                <li>
                    <Link
                        to="https://posthog.com/docs/session-replay/troubleshooting#angular-performance"
                        target="_blank"
                    >
                        Angular performance
                    </Link>
                </li>
            </ul>
        </>
    )
}

function CannotConfigureHelpMessage(): JSX.Element {
    return (
        <>
            <p>
                There are several ways to control which sessions you record:
                <ul className="list-disc pl-4 text-secondary">
                    <li>
                        <Link
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#programmatically-start-and-stop-recordings"
                            target="_blank"
                        >
                            Programmatically start and stop recordings
                        </Link>
                    </li>
                    <li>
                        <Link
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#with-url-trigger-conditions"
                            target="_blank"
                        >
                            With URL trigger conditions
                        </Link>
                    </li>
                    <li>
                        <Link
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#with-event-trigger-conditions"
                            target="_blank"
                        >
                            With Event trigger conditions
                        </Link>
                    </li>
                    <li>
                        <Link
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#with-feature-flags"
                            target="_blank"
                        >
                            With feature flags
                        </Link>
                    </li>
                    <li>
                        <Link
                            to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#sampling"
                            target="_blank"
                        >
                            Sampling
                        </Link>
                    </li>
                </ul>
            </p>
        </>
    )
}

const helpMessages = [
    {
        title: 'Cannot configure to my needs',
        content: <CannotConfigureHelpMessage />,
    },
    {
        title: 'Privacy/Legal concerns',
        content: <PrivacyHelpMessage />,
    },
    {
        title: 'Too expensive',
        content: <TooExpensiveHelpMessage />,
    },
    {
        title: 'Performance issues',
        content: <PerformanceHelpMessage />,
    },
]

export function InternalMultipleChoiceSurvey({ surveyId }: InternalSurveyProps): JSX.Element {
    const logic = internalMultipleChoiceSurveyLogic({ surveyId })
    const { survey, surveyResponse, showThankYouMessage, thankYouMessage, openChoice } = useValues(logic)
    const { handleChoiceChange, handleSurveyResponse, setOpenChoice } = useActions(logic)

    const { askSidePanelMax } = useActions(maxGlobalLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    //Because we want to run A/B test to see does it help users or not
    const isHelpEnabled = featureFlags[FEATURE_FLAGS.REPLAY_SETTINGS_HELP] === 'show'

    if (!survey) {
        return <></>
    }

    return (
        <div className="Popover Popover--padded Popover--appear-done Popover--enter-done my-4">
            <div className="flex gap-4 items-start">
                <div className="Popover__box p-4 min-w-md">
                    {survey.questions.map((question: SurveyQuestion) => (
                        <div key={question.question} className="text-sm">
                            {showThankYouMessage && thankYouMessage}
                            {!showThankYouMessage && (
                                <>
                                    <strong>{question.question}</strong>
                                    {question.type === SurveyQuestionType.MultipleChoice && (
                                        <ul className="list-inside list-none mt-2">
                                            {question.choices.map((choice, index) => {
                                                // Add an open choice text area if the last choice is an open choice
                                                if (index === question.choices.length - 1 && question.hasOpenChoice) {
                                                    return (
                                                        <div className="mt-2" key={choice}>
                                                            <LemonTextArea
                                                                placeholder="Please share any additional comments or feedback"
                                                                onChange={setOpenChoice}
                                                                value={openChoice ?? ''}
                                                                className="my-2"
                                                                data-attr="replay-churn-open-choice-text"
                                                            />
                                                        </div>
                                                    )
                                                }
                                                return (
                                                    <li key={choice}>
                                                        <LemonCheckbox
                                                            onChange={(checked) => handleChoiceChange(choice, checked)}
                                                            label={choice}
                                                            className="font-normal"
                                                            data-attr={`replay-churn-choice-${choice
                                                                .toLowerCase()
                                                                .replace(' ', '-')}`}
                                                        />
                                                    </li>
                                                )
                                            })}
                                        </ul>
                                    )}
                                    <div className="flex gap-2">
                                        <LemonButton
                                            type="primary"
                                            disabledReason={
                                                surveyResponse.length === 0 && openChoice === null
                                                    ? 'Please select at least one option'
                                                    : false
                                            }
                                            onClick={handleSurveyResponse}
                                        >
                                            {question.buttonText ?? 'Submit'}
                                        </LemonButton>
                                        {isHelpEnabled && (
                                            <LemonButton
                                                disabledReason={
                                                    !openChoice || openChoice.length < 5
                                                        ? 'Message must be at least 5 characters'
                                                        : false
                                                }
                                                type="secondary"
                                                onClick={() => {
                                                    askSidePanelMax(
                                                        `I am disabling session replay because of "${openChoice}". Go through PostHog documentation and find a solution to fix this.`
                                                    )
                                                }}
                                            >
                                                Ask PostHog AI for help
                                            </LemonButton>
                                        )}
                                    </div>
                                </>
                            )}
                        </div>
                    ))}
                </div>
                {isHelpEnabled && (
                    <div>
                        {surveyResponse.length > 0 && <h3>Here is how we can help you</h3>}
                        {helpMessages.map((message) => {
                            if (!surveyResponse.includes(message.title)) {
                                return null
                            }
                            return (
                                <div key={message.title} className="mb-4 LemonBanner LemonBanner--info p-4">
                                    <h4>{message.title}</h4>
                                    <div className="font-normal">{message.content}</div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </div>
        </div>
    )
}
