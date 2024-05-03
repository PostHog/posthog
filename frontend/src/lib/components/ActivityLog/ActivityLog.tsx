import './ActivityLog.scss'

import { LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { activityLogLogic, ActivityLogLogicProps } from 'lib/components/ActivityLog/activityLogLogic'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ProductKey } from '~/types'

import { PayGateMini } from '../PayGateMini/PayGateMini'
import { ProductIntroduction } from '../ProductIntroduction/ProductIntroduction'

export type ActivityLogProps = ActivityLogLogicProps & {
    startingPage?: number
    caption?: string | JSX.Element
    renderSideAction?: (logItem: HumanizedActivityLogItem) => JSX.Element
}

const Empty = ({ scope }: { scope: string }): JSX.Element => {
    const noun = scope
        .replace(/([A-Z])/g, ' $1')
        .trim()
        .toLowerCase()

    return (
        <ProductIntroduction
            productName={noun.toUpperCase()}
            productKey={ProductKey.HISTORY}
            thingName="history record"
            description={`History shows any ${noun} changes that have been made. After making changes you'll see them logged here.`}
            isEmpty={true}
        />
    )
}

const SkeletonLog = (): JSX.Element => {
    return (
        <div className="ActivityLogRow items-start">
            <LemonSkeleton.Circle />
            <div className="details space-y-4 mt-2">
                <LemonSkeleton className="w-1/2 h-4" />
                <LemonSkeleton />
            </div>
        </div>
    )
}

const Loading = (): JSX.Element => {
    return (
        <>
            <SkeletonLog />
            <SkeletonLog />
            <SkeletonLog />
            <SkeletonLog />
        </>
    )
}

export const ActivityLogRow = ({
    logItem,
    showExtendedDescription,
    renderSideAction,
}: {
    logItem: HumanizedActivityLogItem
    showExtendedDescription?: boolean
    renderSideAction?: ActivityLogProps['renderSideAction']
}): JSX.Element => {
    return (
        <div className={clsx('ActivityLogRow', logItem.unread && 'ActivityLogRow--unread')}>
            <ProfilePicture
                showName={false}
                user={{
                    first_name: logItem.isSystem ? logItem.name : undefined,
                    email: logItem.email ?? undefined,
                }}
                type={logItem.isSystem ? 'system' : 'person'}
                size="xl"
            />
            <div className="ActivityLogRow__details">
                <div className="ActivityLogRow__description">{logItem.description}</div>
                {showExtendedDescription && logItem.extendedDescription && (
                    <div className="ActivityLogRow__description__extended">{logItem.extendedDescription}</div>
                )}
                <div className="text-muted">
                    <TZLabel time={logItem.created_at} />
                </div>
            </div>
            {renderSideAction?.(logItem)}
        </div>
    )
}

export const ActivityLog = ({
    scope,
    id,
    caption,
    startingPage = 1,
    renderSideAction,
}: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id, caption, startingPage })
    const { humanizedActivity, activityLoading, pagination } = useValues(logic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const paginationState = usePagination(humanizedActivity || [], pagination)

    return (
        <div className="ActivityLog">
            {caption && <div className="page-caption">{caption}</div>}
            <PayGateMini
                feature={AvailableFeature.AUDIT_LOGS}
                overrideShouldShowGate={user?.is_impersonated || !!featureFlags[FEATURE_FLAGS.AUDIT_LOGS_ACCESS]}
            >
                {activityLoading && humanizedActivity.length === 0 ? (
                    <Loading />
                ) : humanizedActivity.length === 0 ? (
                    <Empty scope={scope} />
                ) : (
                    <>
                        <div className="space-y-2">
                            {humanizedActivity.map((logItem, index) => (
                                <ActivityLogRow
                                    key={index}
                                    logItem={logItem}
                                    showExtendedDescription={true}
                                    renderSideAction={renderSideAction}
                                />
                            ))}
                        </div>
                        <LemonDivider />
                        <PaginationControl {...paginationState} nouns={['activity', 'activities']} />
                    </>
                )}
            </PayGateMini>
        </div>
    )
}
