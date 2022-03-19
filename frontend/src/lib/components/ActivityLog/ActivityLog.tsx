import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { TZLabel } from 'lib/components/TimezoneAware'
import { useValues } from 'kea'
import './ActivityLog.scss'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import clsx from 'clsx'
import { Skeleton } from 'antd'

export interface ActivityLogProps {
    scope: 'FeatureFlag'
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number
}

const Empty = (): JSX.Element => (
    <div className="activity-log activity-log__loader">
        <div className="text-muted">There is no history for this item</div>
    </div>
)

const SkeletonLog = (): JSX.Element => {
    return (
        <div className="activity-log-row">
            <Skeleton.Avatar active={true} size={40} />
            <div className="details">
                <Skeleton paragraph={{ rows: 1 }} />
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

export const ActivityLog = ({ scope, id }: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id })
    const { activity, activityLoading } = useValues(logic)
    console.log({ activityLoading })
    return (
        <div className={clsx('activity-log', activityLoading && 'activity-log__loading')}>
            {activity && activity.length ? (
                activity.map((logItem, index) => {
                    return (
                        <div className={'activity-log-row'} key={index}>
                            <ProfilePicture showName={false} email={logItem.email} size={'xl'} />
                            <div className="details">
                                <div>
                                    <strong>{logItem.name ?? 'unknown user'}</strong> {logItem.description}
                                </div>
                                <div className={'text-muted'}>
                                    <TZLabel time={logItem.created_at} />
                                </div>
                            </div>
                        </div>
                    )
                })
            ) : activityLoading ? (
                <Loading />
            ) : (
                <Empty />
            )}
        </div>
    )
}
