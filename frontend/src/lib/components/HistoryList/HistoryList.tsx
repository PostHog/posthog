import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import './HistoryList.scss'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { historyListLogic, HumanizedHistoryListItem } from 'lib/components/HistoryList/historyListLogic'
import { useValues } from 'kea'

interface HistoryListProps {
    type: 'feature_flags'
    id: number
}

export const HistoryList = ({ type, id }: HistoryListProps): JSX.Element => {
    const logic = historyListLogic({ type, id })
    const { history, isLoading } = useValues(logic)

    const columns: LemonTableColumns<HumanizedHistoryListItem> = [
        {
            key: 'profile',
            width: 40,
            render: function Render(_, rowItem: HumanizedHistoryListItem) {
                return <ProfilePicture showName={false} email={rowItem.email} />
            },
        },
        {
            key: 'description',
            render: function Render(_, rowItem: HumanizedHistoryListItem) {
                return (
                    <>
                        <div>
                            <strong>{rowItem.name ?? 'unknown user'}</strong> {rowItem.description}
                        </div>
                        <div className={'muted'}>
                            <TZLabel time={rowItem.created_at} />
                        </div>
                    </>
                )
            },
        },
        {
            key: 'actions',
            render: function Render() {
                return <></>
            },
        },
    ]

    return (
        <>
            <LemonTable
                dataSource={history[id]}
                showHeader={false}
                loading={isLoading}
                columns={columns}
                className="ph-no-capture"
                rowClassName={'history-list-item'}
                rowBorders={false}
            />
        </>
    )
}
