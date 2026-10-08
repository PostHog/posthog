import { workflowsSampleRows } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { WorkflowsWidget } from '../workflows/WorkflowsWidget'

export function WorkflowsWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none shadow-sm">
            <WorkflowsWidget
                tileId={0}
                config={{ limit: 3 }}
                loading={false}
                result={{ results: workflowsSampleRows.slice(0, 3) }}
            />
        </div>
    )
}
