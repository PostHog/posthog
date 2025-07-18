import { IconInfo } from '@posthog/icons'
import { LemonBanner, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

export function SurveyResponseLimitWidget(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { user } = useValues(userLogic)

    if (user?.is_staff || user?.is_impersonated) {
        return null
    }

    // Check if we have survey response usage data
    const surveyResponsesUsage = billing?.usage_summary?.survey_responses
    if (!surveyResponsesUsage) {
        return null
    }

    const { usage = 0, limit = 250 } = surveyResponsesUsage
    const percentageUsed = limit > 0 ? (usage / limit) * 100 : 0
    const remaining = Math.max(0, limit - usage)

    // Don't show if there's no limit (unlimited plan)
    if (!limit) {
        return null
    }

    // Don't show if usage is 0 and we're not near the limit
    if (usage === 0 && percentageUsed < 50) {
        return null
    }

    let bannerType: 'info' | 'warning' | 'error' = 'info'
    if (percentageUsed >= 100) {
        bannerType = 'error'
    } else if (percentageUsed >= 80) {
        bannerType = 'warning'
    }

    return (
        <LemonBanner type={bannerType} className="mb-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span>
                        <strong>Survey Responses This Month:</strong> {usage.toLocaleString()} /{' '}
                        {limit.toLocaleString()}
                    </span>
                    <Tooltip title="Free plan includes 250 survey responses per month. Upgrade for unlimited responses.">
                        <IconInfo className="text-muted" />
                    </Tooltip>
                </div>
                <div className="text-sm text-muted">
                    {remaining > 0 ? `${remaining.toLocaleString()} remaining` : 'Limit reached'}
                </div>
            </div>
            {percentageUsed >= 80 && (
                <div className="mt-2 text-sm">
                    {percentageUsed >= 100 ? (
                        <span>
                            You've reached your monthly limit. Consider{' '}
                            <a href="/organization/billing" className="font-medium underline">
                                upgrading your plan
                            </a>{' '}
                            for unlimited survey responses.
                        </span>
                    ) : (
                        <span>
                            You're approaching your monthly limit. Consider{' '}
                            <a href="/organization/billing" className="font-medium underline">
                                upgrading your plan
                            </a>{' '}
                            for unlimited survey responses.
                        </span>
                    )}
                </div>
            )}
        </LemonBanner>
    )
}
