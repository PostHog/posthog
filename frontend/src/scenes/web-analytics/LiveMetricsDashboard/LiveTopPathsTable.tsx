import { LiveAnimatedTable } from './LiveAnimatedTable'
import { PathItem } from './LiveWebAnalyticsMetricsTypes'

interface LiveTopPathsTableProps {
    paths: PathItem[]
    isLoading: boolean
    className?: string
    totalPageviews: number
}

const renderPathLabel = (item: PathItem): { node: React.ReactNode; tooltipTitle: string } => ({
    node: <span className="font-mono text-xs truncate">{item.path}</span>,
    tooltipTitle: item.path,
})

export const LiveTopPathsTable = ({
    paths,
    isLoading,
    className,
    totalPageviews,
}: LiveTopPathsTableProps): JSX.Element => (
    <LiveAnimatedTable
        items={paths}
        keyExtractor={(item) => item.path}
        viewsExtractor={(item) => item.views}
        renderLabel={renderPathLabel}
        title="Top pages (last 30 minutes)"
        columnLabel="Path"
        emptyMessage="No pageviews recorded in the last 30 minutes"
        isLoading={isLoading}
        totalPageviews={totalPageviews}
        className={className}
    />
)
