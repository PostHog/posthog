import './CompactList.scss'

import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { EmptyMessage, EmptyMessageProps } from '../EmptyMessage/EmptyMessage'

interface CompactListProps {
    title: string | JSX.Element
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
    const { theme } = useValues(themeLogic)
    return (
        <div
            className="CompactList"
            // eslint-disable-next-line react/forbid-dom-props
            style={theme?.boxStyle}
        >
            <div className="CompactList__header">
                <h3 className="px-2 truncate" title={typeof title === 'string' ? title : undefined}>
                    {title}
                </h3>
                {viewAllURL && <LemonButton to={viewAllURL}>View all</LemonButton>}
            </div>
            <div className="mx-2">
                {/* This divider has to be within a div, because otherwise horizontal margin ADDS to the width */}
                <LemonDivider className="my-0" />
            </div>
            <div className="CompactList__content">
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
