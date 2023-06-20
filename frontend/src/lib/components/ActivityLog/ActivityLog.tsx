import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { TZLabel } from 'lib/components/TZLabel'
import { useValues } from 'kea'
import './ActivityLog.scss'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { ActivityScope, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import clsx from 'clsx'
import { ProductIntroduction } from '../ProductIntroduction/ProductIntroduction'
import { ProductKey } from '~/types'
import { LemonDivider } from '@posthog/lemon-ui'

export interface ActivityLogProps {
    scope: ActivityScope
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number | string
    startingPage?: number
    caption?: string | JSX.Element
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
            thingName={'history record'}
            description={`History shows any ${noun} changes that have been made. After making changes you'll see them logged here.`}
            isEmpty={true}
        />
    )
}

const SkeletonLog = (): JSX.Element => {
    return (
        <div className="activity-log-row items-start">
            <LemonSkeleton.Circle />
            <div className="details space-y-4 mt-2">
                <LemonSkeleton className="w-1/2" />
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
}: {
    logItem: HumanizedActivityLogItem
    showExtendedDescription?: boolean
}): JSX.Element => {
    return (
        <div className={clsx('activity-log-row', logItem.unread && 'unread')}>
            <ProfilePicture
                showName={false}
                name={logItem.isSystem ? logItem.name : undefined}
                type={logItem.isSystem ? 'system' : 'person'}
                email={logItem.email ?? undefined}
                size={'xl'}
            />
            <div className="details">
                <div className="activity-description">{logItem.description}</div>
                {showExtendedDescription && logItem.extendedDescription && (
                    <div className="activity-description-extended">{logItem.extendedDescription}</div>
                )}
                <div className={'text-muted'}>
                    <TZLabel time={logItem.created_at} />
                </div>
            </div>
        </div>
    )
}

export const ActivityLog = ({ scope, id, caption, startingPage = 1 }: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id, caption, startingPage })
    const { humanizedActivity, nextPageLoading, pagination } = useValues(logic)

    const paginationState = usePagination(humanizedActivity || [], pagination)

    return (
        <div className="activity-log">
            {caption && <div className="page-caption">{caption}</div>}
            {nextPageLoading && humanizedActivity.length === 0 ? (
                <Loading />
            ) : humanizedActivity.length > 0 ? (
                <>
                    {humanizedActivity.map((logItem, index) => (
                        <ActivityLogRow key={index} logItem={logItem} showExtendedDescription={true} />
                    ))}
                    <LemonDivider />
                    <PaginationControl {...paginationState} nouns={['activity', 'activities']} />
                </>
            ) : (
                <Empty scope={scope} />
            )}
        </div>
    )
}
