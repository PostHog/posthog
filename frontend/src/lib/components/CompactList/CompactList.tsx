import React from 'react'
import './CompactList.scss'
import { LemonDivider } from '../LemonDivider'
import { LemonButton } from '../LemonButton'
import { Skeleton } from 'antd'
import { EmptyMessage, EmptyMessageProps } from '../EmptyMessage/EmptyMessage'

interface CompactListProps {
    title: string
    viewAllURL?: string
    loading: boolean
    items: any[]
    emptyMessage?: EmptyMessageProps
    renderRow: (rowData: any, index: number) => JSX.Element
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
                <LemonDivider />
            </div>
            <div className="scrollable-list">
                {loading ? (
                    <div className="skeleton-container">
                        {Array.from({ length: 6 }, (_, index) => (
                            <Skeleton key={index} active paragraph={false} />
                        ))}
                    </div>
                ) : items.length === 0 && emptyMessage ? (
                    <EmptyMessage {...emptyMessage} />
                ) : (
                    <>{items.map((item, index) => renderRow(item, index))}</>
                )}
            </div>
        </div>
    )
}
