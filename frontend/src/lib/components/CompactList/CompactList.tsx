import './CompactList.scss'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { EmptyMessage, EmptyMessageProps } from '../EmptyMessage/EmptyMessage'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

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
        <div className="compact-list border">
            <div className="compact-list-header">
                <h3>{title}</h3>
                {viewAllURL && <LemonButton to={viewAllURL}>View all</LemonButton>}
            </div>
            <LemonDivider className="mx-2 my-2" />
            <div className="scrollable-list">
                {loading ? (
                    <div className="p-2 space-y-6">
                        {Array.from({ length: 6 }, (_, index) => (
                            <LemonSkeleton key={index} />
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
