import { IconBell, IconGraph, IconRocket, IconTarget } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProfessorHog } from 'lib/components/hedgehogs'
import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'
import { SurveyEditSection, surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'

interface FirstSurveyHelperProps {
    onTabChange?: (tab: string) => void
}

export function FirstSurveyHelper({ onTabChange }: FirstSurveyHelperProps): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { editingSurvey, setSelectedSection, setSurveyValue } = useActions(surveyLogic)
    const { data } = useValues(surveysLogic)

    const hasOnlyOneSurvey = data.surveys.length <= 1

    // Only show for first-time users with unstarted surveys
    if (!hasOnlyOneSurvey || survey.start_date) {
        return null
    }

    return (
        <div className="bg-bg-light border border-border rounded p-4 min-w-full">
            <div className="flex gap-4">
                <div className="flex items-center">
                    <ProfessorHog width={200} height={200} className="scale-x-[-1]" />
                </div>
                <div className="flex-1">
                    <h4 className="text-lg font-semibold mb-3 text-default">Get the most out of your survey</h4>
                    <div className="space-y-1">
                        <div className="flex items-center justify-between">
                            <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                    <IconRocket className="w-4 h-4 text-muted" />
                                    <strong className="text-default">Launch your survey</strong>
                                </div>
                                <p className="text-sm text-muted mb-2">Display your survey to your users.</p>
                            </div>
                            <LaunchSurveyButton>Launch survey</LaunchSurveyButton>
                        </div>
                        <div className="flex items-center justify-between">
                            <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                    <IconTarget className="w-4 h-4 text-muted" />
                                    <strong className="text-default">Add targeting conditions</strong>
                                </div>
                                <p className="text-sm text-muted mb-2">
                                    Show your survey to specific users or on certain pages.{' '}
                                    <Link
                                        to="https://posthog.com/docs/surveys/creating-surveys#display-conditions"
                                        target="_blank"
                                    >
                                        Learn more
                                    </Link>
                                </p>
                            </div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    editingSurvey(true)
                                    setSelectedSection(SurveyEditSection.DisplayConditions)
                                    setTimeout(() => {
                                        setSurveyValue('conditions', { url: '' })
                                    }, 100)
                                }}
                            >
                                Edit survey
                            </LemonButton>
                        </div>
                        <div className="flex items-center justify-between">
                            <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                    <IconGraph className="w-4 h-4 text-muted" />
                                    <strong className="text-default">Preview your results</strong>
                                </div>
                                <p className="text-sm text-muted mb-2">
                                    See how your analytics will look before launching.{' '}
                                    <Link
                                        to="https://posthog.com/docs/surveys/viewing-results#1-on-the-survey-page"
                                        target="_blank"
                                    >
                                        Learn more
                                    </Link>
                                </p>
                            </div>
                            <LemonButton type="secondary" size="small" onClick={() => onTabChange?.('results')}>
                                View demo
                            </LemonButton>
                        </div>
                        <div className="flex items-center justify-between">
                            <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                    <IconBell className="w-4 h-4 text-muted" />
                                    <strong className="text-default">Set up notifications</strong>
                                </div>
                                <p className="text-sm text-muted mb-2">
                                    Get alerted instantly when responses come in.{' '}
                                    <Link to="https://posthog.com/tutorials/slack-surveys" target="_blank">
                                        Slack tutorial
                                    </Link>
                                </p>
                            </div>
                            <LemonButton type="secondary" size="small" onClick={() => onTabChange?.('notifications')}>
                                Set up
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
