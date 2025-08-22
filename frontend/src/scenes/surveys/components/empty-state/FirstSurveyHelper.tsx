import { useActions, useValues } from 'kea'

import { IconBell, IconGraph, IconRocket, IconTarget } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

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
        <div className="bg-bg-light border border-border rounded-lg p-6">
            <div className="flex items-center gap-6">
                <div className="hidden sm:block flex-shrink-0">
                    <ProfessorHog width={180} height={180} className="scale-x-[-1]" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="mb-6">
                        <h3 className="text-xl font-semibold mb-2 text-default">Ready to launch your survey?</h3>
                        <p className="text-sm text-muted">
                            Your survey is set up! Here's what you can do next to maximize your results.
                        </p>
                    </div>

                    {/* Primary Action - Most Important */}
                    <div className="bg-primary-3000/5 border border-primary-3000/20 rounded-lg p-4 mb-4">
                        <div className="flex items-center gap-3">
                            <div className="flex items-center justify-center w-8 h-8 bg-primary-3000 rounded-lg flex-shrink-0">
                                <IconRocket className="w-4 h-4 text-white" />
                            </div>
                            <div className="flex-1 min-w-0">
                                <h4 className="font-semibold text-default mb-0">Launch your survey</h4>
                                <p className="text-sm text-muted mb-0">
                                    Start collecting feedback from your users right away.
                                </p>
                            </div>
                            <div className="flex-shrink-0">
                                <LaunchSurveyButton>Launch survey</LaunchSurveyButton>
                            </div>
                        </div>
                    </div>

                    {/* Secondary Actions - Grouped */}
                    <div className="space-y-3">
                        <h5 className="text-sm font-medium text-muted uppercase tracking-wide">
                            Optional improvements
                        </h5>

                        <div className="grid gap-3 sm:grid-cols-3">
                            <div className="border border-border rounded-lg p-3 hover:border-border-bold transition-colors">
                                <div className="flex items-start gap-3">
                                    <IconTarget className="w-4 h-4 text-muted mt-1 flex-shrink-0" />
                                    <div className="min-w-0 flex-1">
                                        <h4 className="font-medium text-default text-sm mb-1">
                                            Add display conditions
                                        </h4>
                                        <p className="text-xs text-muted mb-2 leading-relaxed">
                                            Show to specific users.{' '}
                                            <Link
                                                to="https://posthog.com/docs/surveys/creating-surveys#display-conditions"
                                                target="_blank"
                                                className="text-primary-3000"
                                            >
                                                Docs
                                            </Link>
                                        </p>
                                        <LemonButton
                                            type="tertiary"
                                            size="xsmall"
                                            onClick={() => {
                                                editingSurvey(true)
                                                setSelectedSection(SurveyEditSection.DisplayConditions)
                                                setTimeout(() => {
                                                    setSurveyValue('conditions', { url: '' })
                                                }, 100)
                                            }}
                                        >
                                            Configure
                                        </LemonButton>
                                    </div>
                                </div>
                            </div>

                            <div className="border border-border rounded-lg p-3 hover:border-border-bold transition-colors">
                                <div className="flex items-start gap-3">
                                    <IconGraph className="w-4 h-4 text-muted mt-1 flex-shrink-0" />
                                    <div className="min-w-0 flex-1">
                                        <h4 className="font-medium text-default text-sm mb-1">Preview results</h4>
                                        <p className="text-xs text-muted mb-2 leading-relaxed">
                                            See sample analytics.{' '}
                                            <Link
                                                to="https://posthog.com/docs/surveys/viewing-results#1-on-the-survey-page"
                                                target="_blank"
                                                className="text-primary-3000"
                                            >
                                                Docs
                                            </Link>
                                        </p>
                                        <LemonButton
                                            type="tertiary"
                                            size="xsmall"
                                            onClick={() => onTabChange?.('results')}
                                        >
                                            View demo
                                        </LemonButton>
                                    </div>
                                </div>
                            </div>

                            <div className="border border-border rounded-lg p-3 hover:border-border-bold transition-colors">
                                <div className="flex items-start gap-3">
                                    <IconBell className="w-4 h-4 text-muted mt-1 flex-shrink-0" />
                                    <div className="min-w-0 flex-1">
                                        <h4 className="font-medium text-default text-sm mb-1">
                                            Get notified on responses
                                        </h4>
                                        <p className="text-xs text-muted mb-2 leading-relaxed">
                                            Slack notifications.{' '}
                                            <Link
                                                to="https://posthog.com/tutorials/slack-surveys"
                                                target="_blank"
                                                className="text-primary-3000"
                                            >
                                                Tutorial
                                            </Link>
                                        </p>
                                        <LemonButton
                                            type="tertiary"
                                            size="xsmall"
                                            onClick={() => onTabChange?.('notifications')}
                                        >
                                            Set up
                                        </LemonButton>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
