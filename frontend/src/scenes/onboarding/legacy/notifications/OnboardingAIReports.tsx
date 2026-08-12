import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCollapse } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { OnboardingStepKey } from '~/types'

import { OnboardingStepComponentType } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { onboardingAIReportsLogic } from './onboardingAIReportsLogic'

export const OnboardingAIReports: OnboardingStepComponentType = () => {
    const { user } = useValues(userLogic)
    const { report, createdSubscriptionId, createdSubscriptionIdLoading } = useValues(onboardingAIReportsLogic)
    const { createReportSubscription, removeReportSubscription } = useActions(onboardingAIReportsLogic)

    const subscribed = createdSubscriptionId !== null

    return (
        <OnboardingStep
            title="Get a weekly report"
            subtitle="We can email you a written summary every week, based on what you told us you do. Reports start once your data is flowing, so it's fine to set this up before you've sent any events."
            stepKey={OnboardingStepKey.AI_REPORTS}
            continueText={subscribed ? undefined : 'Skip for now'}
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4">
                <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                        <h3 className="m-0 text-base font-semibold">{report.headline}</h3>
                        <p className="m-0 text-sm text-muted">{report.lead}</p>
                    </div>
                    {!subscribed && (
                        <LemonButton
                            type="primary"
                            onClick={() => createReportSubscription()}
                            loading={createdSubscriptionIdLoading}
                            data-attr="onboarding-ai-report-subscribe"
                        >
                            Email me this weekly
                        </LemonButton>
                    )}
                </div>

                {subscribed ? (
                    <div className="flex items-center justify-between gap-2 rounded border bg-surface-primary p-2">
                        <div className="flex items-center gap-2">
                            <IconCheckCircle className="text-success shrink-0 text-lg" />
                            <span className="text-sm">
                                Done. Your first report arrives next week at {user?.email}. You can change or cancel it
                                anytime in Notifications &amp; alerts.
                            </span>
                        </div>
                        <LemonButton
                            size="small"
                            onClick={() => removeReportSubscription()}
                            loading={createdSubscriptionIdLoading}
                            data-attr="onboarding-ai-report-undo"
                        >
                            Undo
                        </LemonButton>
                    </div>
                ) : (
                    <LemonCollapse
                        size="small"
                        panels={[
                            {
                                key: 'prompt',
                                header: 'What it covers',
                                content: <p className="m-0 text-sm">{report.prompt}</p>,
                            },
                        ]}
                    />
                )}
            </LemonCard>
        </OnboardingStep>
    )
}

OnboardingAIReports.stepKey = OnboardingStepKey.AI_REPORTS
