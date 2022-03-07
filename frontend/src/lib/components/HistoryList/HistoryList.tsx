import React from 'react'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { historyListLogic, HumanizedHistoryListItem } from 'lib/components/HistoryList/historyListLogic'
import { useValues } from 'kea'

interface HistoryListProps {
    type: 'FeatureFlag'
    id: number
}

export const HistoryList = ({ type, id }: HistoryListProps): JSX.Element => {
    const logic = historyListLogic({ type, id })
    const { history, historyLoading } = useValues(logic)

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
                        <div className={'text-muted'}>
                            <TZLabel time={rowItem.created_at} />
                        </div>
                    </>
                )
            },
        },
    ]

    return (
        <LemonTable
            dataSource={history}
            showHeader={false}
            loading={historyLoading}
            columns={columns}
            className="ph-no-capture"
            rowClassName={'history-list-item'}
            rowBorders={false}
        />
    )
}
