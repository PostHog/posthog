import React from 'react'
import './CompactList.scss'
import { LemonSpacer } from '../LemonRow'
import { LemonButton } from '../LemonButton'
import { Skeleton } from 'antd'
import { EmptyMessage, EmptyMessageProps } from '../EmptyMessage/EmptyMessage'

interface CompactListProps {
    title: string
    viewAllURL?: string
    loading: boolean
    items: any[]
    emptyMessage?: EmptyMessageProps
    renderRow: (rowData: any) => JSX.Element
}

export function CompactList({
    title,
    viewAllURL,
    loading,
    items,
    emptyMessage,
    renderRow,
}: CompactListProps): JSX.Element {
    return (
        <div className="compact-list">
            <div className="compact-list-header">
                <h3>{title}</h3>
                {viewAllURL && <LemonButton to={viewAllURL}>View all</LemonButton>}
            </div>
            <div className="spacer-container">
                <LemonSpacer />
            </div>
            <div className="scrollable-list">
                {loading ? (
                    <>
                        {Array.from({ length: 6 }, (_, index) => (
                            <Skeleton key={index} active paragraph={false} />
                        ))}
                    </>
                ) : items.length === 0 && emptyMessage ? (
                    <EmptyMessage {...emptyMessage} />
                ) : (
                    <>{items.map((item) => renderRow(item))}</>
                )}
            </div>
        </div>
    )
}
