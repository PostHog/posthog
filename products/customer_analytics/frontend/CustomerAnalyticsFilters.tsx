import { Tooltip } from '@posthog/lemon-ui'

import { FilterBar } from 'lib/components/FilterBar'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

export function CustomerAnalyticsFilters(): JSX.Element {
    return (
        <FilterBar
            right={
                <Tooltip title="Refresh data">
                    <ReloadAll />
                </Tooltip>
            }
        />
    )
}
