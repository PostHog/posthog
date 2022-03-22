import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { TZLabel } from 'lib/components/TimezoneAware'
import { useValues } from 'kea'
import './ActivityLog.scss'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { Skeleton } from 'antd'
import { Describer } from 'lib/components/ActivityLog/humanizeActivity'
import { PaginationControl, usePagination } from 'lib/components/PaginationControl'

export interface ActivityLogProps {
    scope: 'FeatureFlag'
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number
    describer?: Describer
    startingPage?: number
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

export const ActivityLog = ({ scope, id, describer, startingPage = 1 }: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id, describer, startingPage })
    const { humanizedActivity, nextPageLoading, pagination } = useValues(logic)
    const paginationState = usePagination(humanizedActivity || [], pagination)

    return (
        <div className="activity-log">
            {nextPageLoading && humanizedActivity.length === 0 ? (
                <Loading />
            ) : humanizedActivity.length > 0 ? (
                <>
                    {humanizedActivity.map((logItem, index) => {
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
                    })}
                    <PaginationControl {...paginationState} nouns={['activity', 'activities']} />
                </>
            ) : (
                <Empty />
            )}
        </div>
    )
}
