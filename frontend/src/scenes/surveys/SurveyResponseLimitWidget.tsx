import { IconInfo } from '@posthog/icons'
import { LemonBanner, Link, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

const DEFAULT_SURVEY_RESPONSE_LIMIT = 250

export function SurveyResponseLimitWidget(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { user } = useValues(userLogic)

    // Only show for non-admin users
    if (user?.is_staff || user?.is_impersonated) {
        return null
    }

    // Check if we have survey response usage data
    const surveyResponsesUsage = billing?.usage_summary?.survey_responses
    if (!surveyResponsesUsage) {
        return null
    }

    const { usage = 0, limit = DEFAULT_SURVEY_RESPONSE_LIMIT } = surveyResponsesUsage
    const percentageUsed = (usage / limit) * 100
    const remaining = limit - usage

    // Don't show if no usage and not approaching limit
    if (usage === 0 && percentageUsed < 80) {
        return null
    }

    let bannerType: 'info' | 'warning' | 'error' = 'info'
    let message = `Survey Responses This Month: ${usage} / ${limit}`

    if (percentageUsed >= 100) {
        bannerType = 'error'
        message = `You've reached your monthly limit of ${limit} survey responses.`
    } else if (percentageUsed >= 80) {
        bannerType = 'warning'
        message = `You're approaching your monthly limit: ${usage} / ${limit} responses used.`
    }

    return (
        <LemonBanner type={bannerType} className="mb-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span>{message}</span>
                    {remaining > 0 && percentageUsed < 100 && (
                        <span className="text-sm text-muted">({remaining} responses left)</span>
                    )}
                    <Tooltip title="Survey responses are limited to 250 per month on the free plan. Upgrade to get unlimited responses.">
                        <IconInfo className="text-muted" />
                    </Tooltip>
                </div>
                {percentageUsed >= 80 && (
                    <Link to="/organization/billing" className="font-medium underline">
                        upgrading your plan
                    </Link>
                )}
            </div>
        </LemonBanner>
    )
}
