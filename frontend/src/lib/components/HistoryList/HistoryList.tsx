import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { TZLabel } from 'lib/components/TimezoneAware'
import { historyListLogic } from 'lib/components/HistoryList/historyListLogic'
import { useValues } from 'kea'
import './HistoryList.scss'
import { Spinner } from 'lib/components/Spinner/Spinner'

export interface HistoryListProps {
    type: 'FeatureFlag'
    id: number
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

export const HistoryList = ({ type, id }: HistoryListProps): JSX.Element | null => {
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

    return <div className="history-list">{rows && rows.length ? rows : historyLoading ? <Loading /> : <Empty />}</div>
}
