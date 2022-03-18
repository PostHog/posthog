import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { TZLabel } from 'lib/components/TimezoneAware'
import { useValues } from 'kea'
import './ActivityLog.scss'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'

export interface ActivityLogProps {
    scope: 'FeatureFlag'
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number
}

const Empty = (): JSX.Element => (
    <div className="history-list">
        <div className="text-muted">There is no history for this item</div>
    </div>
)

const Loading = (): JSX.Element => (
    <div className="text-muted">
        <Spinner size="sm" style={{ verticalAlign: 'sub' }} /> Loading history for this item
    </div>
)

export const ActivityLog = ({ scope, id }: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id })
    const { activity, activityLoading } = useValues(logic)

    return (
        <div className="history-list">
            {activity && activity.length ? (
                activity.map((logItem, index) => {
                    return (
                        <div className={'history-list-row'} key={index}>
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
