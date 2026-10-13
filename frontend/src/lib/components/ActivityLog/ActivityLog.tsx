import './ActivityLog.scss'

import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { ActivityLogLogicProps, activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType, AvailableFeature } from '~/types'

import { AccessDenied } from '../AccessDenied'
import { PayGateMini } from '../PayGateMini/PayGateMini'
import { ProductIntroduction } from '../ProductIntroduction/ProductIntroduction'
import { ActivityLogRow } from './ActivityLogRow'

export type ActivityLogProps = ActivityLogLogicProps & {
    startingPage?: number
    caption?: string | JSX.Element
}

const Empty = ({ scope }: { scope: string | string[] }): JSX.Element => {
    const noun = (Array.isArray(scope) ? scope[0] : scope)
        .replace(/([A-Z])/g, ' $1')
        .trim()
        .toLowerCase()

    return (
        <ProductIntroduction
            thingName="history record"
            description={`History shows any ${noun} changes that have been made. After making changes you'll see them logged here.`}
            isEmpty={true}
        />
    )
}

export const SkeletonLog = (): JSX.Element => {
    return (
        <div className="ActivityLogRow items-start">
            <LemonSkeleton.Circle />
            <div className="details deprecated-space-y-4 mt-2">
                <LemonSkeleton className="w-1/2 h-4" />
                <LemonSkeleton />
            </div>
        </div>
    )
}

const Loading = (): JSX.Element => {
    return (
        <div className="space-y-4">
            <SkeletonLog />
            <SkeletonLog />
            <SkeletonLog />
            <SkeletonLog />
        </div>
    )
}

export const ActivityLog = ({ scope, id, caption, startingPage = 1 }: ActivityLogProps): JSX.Element | null => {
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const hasAccess = userHasAccess(AccessControlResourceType.ActivityLog, AccessControlLevel.Viewer)

    if (!hasAccess) {
        return <AccessDenied object="activity logs" />
    }

    return (
        <div className="ActivityLog" data-attr="activity-log">
            {caption && <div className="page-caption">{caption}</div>}
            <PayGateMini
                feature={AvailableFeature.AUDIT_LOGS}
                featureDetail="activity-log"
                overrideShouldShowGate={user?.is_impersonated || !!featureFlags[FEATURE_FLAGS.AUDIT_LOGS_ACCESS]}
            >
                <ActivityLogContents scope={scope} id={id} caption={caption} startingPage={startingPage} />
            </PayGateMini>
        </div>
    )
}

const ActivityLogContents = ({ scope, id, caption, startingPage = 1 }: ActivityLogProps): JSX.Element => {
    const logic = activityLogLogic({ scope, id, caption, startingPage })
    const { humanizedActivity, activityLoading, pagination, highlightedActivityId } = useValues(logic)

    const paginationState = usePagination(humanizedActivity || [], pagination)

    if (activityLoading && humanizedActivity.length === 0) {
        return <Loading />
    }

    if (humanizedActivity.length === 0) {
        return <Empty scope={scope} />
    }

    return (
        <>
            <div className="deprecated-space-y-2">
                {humanizedActivity.map((logItem, index) => (
                    <ActivityLogRow
                        key={logItem.id || index}
                        logItem={logItem}
                        highlighted={logItem.id === highlightedActivityId}
                    />
                ))}
            </div>
            <LemonDivider />
            <PaginationControl {...paginationState} nouns={['activity', 'activities']} />
        </>
    )
}
