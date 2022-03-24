import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { TZLabel } from 'lib/components/TimezoneAware'
import { useValues } from 'kea'
import './ActivityLog.scss'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { Skeleton } from 'antd'
import { Describer } from 'lib/components/ActivityLog/humanizeActivity'

export interface ActivityLogProps {
    scope: 'FeatureFlag' | 'Person'
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number
    describer?: Describer
    caption?: string | JSX.Element
}

const Empty = ({ scope }: { scope: string }): JSX.Element => {
    const noun = scope
        .replace(/([A-Z])/g, ' $1')
        .trim()
        .toLowerCase()
    return (
        <div className="empty">
            <h1>There is no history for this {noun}</h1>
            <div>As changes are made to this {noun}, they'll show up here</div>
        </div>
    )
}

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

export const ActivityLog = ({ scope, id, describer, caption }: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id, describer })
    const { activity, activityLoading } = useValues(logic)
    return (
        <div className="activity-log">
            {caption && <div className="page-caption">{caption}</div>}
            {activityLoading ? (
                <Loading />
            ) : activity.length > 0 ? (
                activity.map((logItem, index) => {
                    return (
                        <div className={'activity-log-row'} key={index}>
                            <ProfilePicture showName={false} email={logItem.email} size={'xl'} />
                            <div className="details">
                                <div className="activity-description">
                                    <div>
                                        <strong>{logItem.name ?? 'unknown user'}</strong>
                                    </div>{' '}
                                    {logItem.description}
                                </div>
                                <div className={'text-muted'}>
                                    <TZLabel time={logItem.created_at} />
                                </div>
                            </div>
                        </div>
                    )
                })
            ) : (
                <Empty scope={scope} />
            )}
        </div>
    )
}
