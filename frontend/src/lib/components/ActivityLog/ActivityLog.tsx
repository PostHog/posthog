import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { TZLabel } from 'lib/components/TimezoneAware'
import { useValues } from 'kea'
import './ActivityLog.scss'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import clsx from 'clsx'
import { Skeleton } from 'antd'
import { Describer } from 'lib/components/ActivityLog/humanizeActivity'

export interface ActivityLogProps {
    scope: 'FeatureFlag'
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number
    describer?: Describer
}

const Empty = (): JSX.Element => <div className="text-muted">There is no history for this item</div>

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

export const ActivityLog = ({ scope, id, describer }: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id, describer })
    const { activity, activityLoading } = useValues(logic)
    const activityRows = activity.map((logItem, index) => {
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

    return (
        <div className={clsx('activity-log', activityLoading && 'activity-log__loading')}>
            <div className="activity-log__loader" />
            {activityLoading ? <Loading /> : activity.length > 0 ? activityRows : <Empty />}
        </div>
    )
}
