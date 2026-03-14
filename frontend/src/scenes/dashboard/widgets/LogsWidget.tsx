import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'

interface LogsWidgetProps {
    tileId: number
    config: Record<string, any>
}

function LogsWidget({ tileId, config }: LogsWidgetProps): JSX.Element {
    return (
        <div className="h-full w-full overflow-hidden">
            <LogsViewer
                id={`dashboard-widget-${tileId}`}
                showFullScreenButton={false}
                initialFilters={config.filters}
            />
        </div>
    )
}

export default LogsWidget
