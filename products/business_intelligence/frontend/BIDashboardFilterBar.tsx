import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'

export function BIDashboardFilterBar({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { enabled, selection, targets } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
    const { setEnabled, setSelection } = useActions(biDashboardCrossFilterLogic({ dashboardId }))
    return (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded border p-3" data-attr="bi-dashboard-filter-bar">
            <LemonSwitch checked={enabled} onChange={setEnabled} label="Use worksheets as filters" />
            {enabled && (
                <>
                    <span className="text-secondary text-xs">
                        Click a mark to filter other worksheets on the same data source. Click again to clear.
                    </span>
                    {selection && (
                        <div className="flex w-full flex-wrap items-center gap-2" role="status">
                            <span className="min-w-0 truncate font-semibold">{selection.title}</span>
                            {selection.selection.labels.map(({ name, value }, index) => (
                                <LemonTag key={index} className="max-w-full">
                                    <span className="truncate">{`${name}: ${value}`}</span>
                                </LemonTag>
                            ))}
                            <span>{`${Object.keys(targets).length} worksheets filtered`}</span>
                            <LemonButton size="xsmall" onClick={() => setSelection(null)}>
                                Clear selection
                            </LemonButton>
                        </div>
                    )}
                    <span className="w-full text-xs text-secondary">
                        Temporary exploration only. The source chart and other tile types stay unchanged. Selections are
                        not saved, shared, or exported.
                    </span>
                </>
            )}
        </div>
    )
}
