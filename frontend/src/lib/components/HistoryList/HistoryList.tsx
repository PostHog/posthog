import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { TZLabel } from 'lib/components/TimezoneAware'
import { historyListLogic } from 'lib/components/HistoryList/historyListLogic'
import { useValues } from 'kea'
import './HistoryList.scss'
import { Spinner } from 'lib/components/Spinner/Spinner'

interface HistoryListProps {
    type: 'FeatureFlag'
    id: number
}

export const HistoryList = ({ type, id }: HistoryListProps): JSX.Element => {
    const logic = historyListLogic({ type, id })
    const { history, historyLoading } = useValues(logic)

    const rows = history.map((historyItem, index) => {
        return (
            <div className={'history-list-row'} key={index}>
                <ProfilePicture showName={false} email={historyItem.email} size={'xl'} />
                <div className="details">
                    <div>
                        <strong>{historyItem.name ?? 'unknown user'}</strong> {historyItem.description}
                    </div>
                    <div className={'text-muted'}>
                        <TZLabel time={historyItem.created_at} />
                    </div>
                </div>
            </div>
        )
    })

    return (
        <div className="history-list">
            {rows && rows.length ? (
                rows
            ) : historyLoading ? (
                <div className="empty-state">
                    <Spinner size="sm" /> Loading history for this item
                </div>
            ) : (
                <div className="empty-state">There is no history for this item</div>
            )}
        </div>
    )
}
