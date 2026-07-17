import { useMountedLogic, useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SurveyLogicProps, surveyLogic } from '../surveyLogic'
import { URL_AUDIENCE_ESTIMATE_DAYS, surveyUrlAudienceEstimateLogic } from '../surveyUrlAudienceEstimateLogic'

/** Estimated unique users who viewed pages matching the survey's URL condition. Must be rendered
 * within a `BindLogic` for `surveyLogic`, and only on editing surfaces — mounting it is what
 * triggers the estimate queries. */
export function SurveyUrlAudienceEstimate({ className }: { className?: string }): JSX.Element | null {
    const boundSurveyLogic = useMountedLogic(surveyLogic)
    const { urlAudienceEstimate } = useValues(
        surveyUrlAudienceEstimateLogic(boundSurveyLogic.props as SurveyLogicProps)
    )

    if (urlAudienceEstimate.status === 'idle') {
        return null
    }

    if (urlAudienceEstimate.status === 'loading') {
        return (
            <p className={cn('text-xs text-muted flex items-center gap-1', className)}>
                <Spinner className="text-xs" /> Estimating matching users...
            </p>
        )
    }

    if (urlAudienceEstimate.status === 'error') {
        return (
            <p className={cn('text-xs text-muted', className)}>
                Unable to estimate matching users for this URL condition.
            </p>
        )
    }

    return (
        <p className={cn('text-xs text-muted', className)}>
            About {humanFriendlyNumber(urlAudienceEstimate.count)} unique{' '}
            {urlAudienceEstimate.count === 1 ? 'user' : 'users'} viewed matching URLs in the last{' '}
            {URL_AUDIENCE_ESTIMATE_DAYS} days.
        </p>
    )
}
