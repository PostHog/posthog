import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Survey } from '~/types'

import { SurveyAppearancePreview } from '../../SurveyAppearancePreview'

interface SuccessStepProps {
    survey: Survey
}

export function SuccessStep({ survey }: SuccessStepProps): JSX.Element {
    const [countdown, setCountdown] = useState(5)

    useEffect(() => {
        if (!survey?.id) {
            return
        }

        const interval = setInterval(() => {
            setCountdown((c) => c - 1)
        }, 1000)

        const timer = setTimeout(() => {
            router.actions.push(urls.survey(survey.id))
        }, 5000)

        return () => {
            clearInterval(interval)
            clearTimeout(timer)
        }
    }, [survey?.id])

    return (
        <div className="text-center space-y-6">
            <div className="space-y-2">
                <h1 className="text-2xl font-semibold">Your survey is live!</h1>
                <p className="text-secondary">Responses will start coming in based on your targeting settings.</p>
                <p className="text-muted text-sm">Redirecting to your survey in {countdown}...</p>
            </div>

            <div className="flex items-center justify-center gap-4">
                <LemonButton type="primary" to={urls.survey(survey.id)}>
                    View survey now
                </LemonButton>
                <LemonButton to={urls.surveyTemplates()}>Create another survey</LemonButton>
            </div>

            <div className="flex justify-center">
                <SurveyAppearancePreview survey={survey} previewPageIndex={0} />
            </div>

            <div className="bg-bg-3000 rounded-lg p-4 text-left max-w-md mx-auto space-y-2">
                <h3 className="font-medium">Summary</h3>
                <dl className="space-y-1 text-sm">
                    <div className="flex justify-between">
                        <dt className="text-secondary">Showing on</dt>
                        <dd>{survey.conditions?.url || 'All pages'}</dd>
                    </div>
                    <div className="flex justify-between">
                        <dt className="text-secondary">Frequency</dt>
                        <dd>
                            {survey.conditions?.seenSurveyWaitPeriodInDays == null
                                ? 'Once ever'
                                : `Every ${survey.conditions?.seenSurveyWaitPeriodInDays} days`}
                        </dd>
                    </div>
                </dl>
            </div>
        </div>
    )
}
