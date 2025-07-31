import { IconInfo } from '@posthog/icons'
import { LemonBanner, Link, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'
import { organizationLogic } from 'scenes/organizationLogic'

export function SurveyResponseLimitWidget(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { user } = useValues(userLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)

    // Only hide when impersonating, show for all other users (including admins)
    if (user?.is_impersonated) {
        return null
    }

    // Check if we have survey response usage data
    const surveyResponsesUsage = billing?.usage_summary?.survey_responses
    if (!surveyResponsesUsage?.usage) {
        return null
    }

    const { usage = 0, limit } = surveyResponsesUsage
    const percentageUsed = limit ? (usage / limit) * 100 : 0

    let type: 'info' | 'warning' | 'error' = 'info'
    let message: string

    if (usage === 0) {
        message = `You have used 0 responses this month.`
    } else if (limit && usage >= limit) {
        type = 'error'
        message = `You have used all ${limit} responses this month. Further responses will not be collected.`
    } else if (limit && percentageUsed >= 80) {
        type = 'warning'
        message = `You have used ${usage} of ${limit} responses this month. You have ${
            limit - usage
        } responses remaining.`
    } else if (limit) {
        message = `You have used ${usage} of ${limit} responses this month. You have ${
            limit - usage
        } responses remaining.`
    } else {
        message = `You have used ${usage} responses this month.`
    }

    return (
        <LemonBanner
            type={type}
            action={
                isAdminOrOwner ? (
                    <Link to="/organization/billing" className="font-semibold">
                        View billing details
                    </Link>
                ) : undefined
            }
            className="mb-4"
        >
            {message}
        </LemonBanner>
    )
}
