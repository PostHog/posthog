import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { TZLabel } from 'lib/components/TimezoneAware'
import { useValues } from 'kea'
import './ActivityLog.scss'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { ActivityScope, Describer } from 'lib/components/ActivityLog/humanizeActivity'
import { PaginationControl, usePagination } from 'lib/components/PaginationControl'
import { LemonSkeleton } from '../LemonSkeleton'

export interface ActivityLogProps {
    scope: ActivityScope
    // if no id is provided, the list is not scoped by id and shows all activity ordered by time
    id?: number | string
    describer?: Describer
    startingPage?: number
    caption?: string | JSX.Element
}

const Empty = ({ scope, idExists }: { scope: string; idExists: boolean }): JSX.Element => {
    const noun = scope
        .replace(/([A-Z])/g, ' $1')
        .trim()
        .toLowerCase()

    // KLUDGE: Appending 's' to the noun works with all values for ActivityScope at the moment, but might not make sense as more models are added
    return (
        <div className="empty">
            {idExists ? (
                <>
                    <h1>There is no history for this {noun}</h1>
                    <div>As changes are made to this {noun}, they'll show up here</div>
                </>
            ) : (
                <>
                    <h1>There is no history yet for {noun + 's'}</h1>
                    <div>As changes are made to {noun + 's'}, they'll show up here</div>
                </>
            )}
        </div>
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

export const ActivityLog = ({
    scope,
    id,
    describer,
    caption,
    startingPage = 1,
}: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id, describer, caption, startingPage })
    const { humanizedActivity, nextPageLoading, pagination } = useValues(logic)

    const paginationState = usePagination(humanizedActivity || [], pagination)

    return (
        <div className="activity-log">
            {caption && <div className="page-caption">{caption}</div>}
            {nextPageLoading && humanizedActivity.length === 0 ? (
                <Loading />
            ) : humanizedActivity.length > 0 ? (
                <>
                    {humanizedActivity.map((logItem, index) => {
                        return (
                            <div className={'activity-log-row'} key={index}>
                                <ProfilePicture showName={false} email={logItem.email} size={'xl'} />
                                <div className="details">
                                    <div className="activity-description">{logItem.description}</div>
                                    {logItem.extendedDescription && (
                                        <div className="activity-description-extended">
                                            {logItem.extendedDescription}
                                        </div>
                                    )}
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
                <Empty scope={scope} idExists={typeof id !== 'undefined'} />
            )}
        </div>
    )
}
