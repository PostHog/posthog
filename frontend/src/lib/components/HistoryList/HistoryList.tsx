import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import './HistoryList.scss'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { HumanizedHistoryListItem } from 'lib/components/HistoryList/historyListLogic'

interface HistoryListProps {
    history: HumanizedHistoryListItem[]
}

export const HistoryList = ({ history }: HistoryListProps): JSX.Element => {
    const columns: LemonTableColumns<HumanizedHistoryListItem> = [
        {
            key: 'profile',
            width: 40,
            render: function Render(_, item: HumanizedHistoryListItem) {
                return <ProfilePicture showName={false} email={item.email} />
            },
        },
        {
            key: 'description',
            render: function Render(_, item: HumanizedHistoryListItem) {
                return (
                    <>
                        <div>
                            <strong>{item.name ?? 'unknown user'}</strong> {item.description}
                        </div>
                        <div className={'muted'}>
                            <TZLabel time={item.created_at} />
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
                dataSource={history}
                showHeader={false}
                loading={false}
                columns={columns}
                className="ph-no-capture"
                rowClassName={'history-list-item'}
                rowBorders={false}
            />
        </>
    )
}
