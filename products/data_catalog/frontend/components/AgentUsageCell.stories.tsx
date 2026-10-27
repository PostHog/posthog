import type { Meta, StoryObj } from '@storybook/react'

import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { AgentUsageCell } from './AgentUsageCell'

function metric(overrides: Partial<DataCatalogMetricApi>): DataCatalogMetricApi {
    return {
        name: 'weekly_active_users',
        status: 'approved',
        is_drifted: false,
        runs_30d: 0,
        ai_runs_30d: 0,
        ...overrides,
    } as DataCatalogMetricApi
}

const meta: Meta<typeof AgentUsageCell> = {
    title: 'Data catalog/Agent usage cell',
    component: AgentUsageCell,
    parameters: { viewMode: 'story' },
}
export default meta

export const AllStates: StoryObj<typeof AgentUsageCell> = {
    render: () => (
        <div className="flex flex-col items-start gap-4 p-4 w-80">
            <AgentUsageCell
                metric={metric({ runs_30d: 40, ai_runs_30d: 31 })}
                warned={false}
                cleanupCandidate={false}
            />
            <AgentUsageCell
                metric={metric({ status: 'proposed', runs_30d: 12, ai_runs_30d: 12 })}
                warned
                cleanupCandidate={false}
            />
            <AgentUsageCell
                metric={metric({ is_drifted: true, runs_30d: 5, ai_runs_30d: 1 })}
                warned
                cleanupCandidate={false}
            />
            <AgentUsageCell metric={metric({})} warned={false} cleanupCandidate={false} />
            <AgentUsageCell metric={metric({})} warned={false} cleanupCandidate />
        </div>
    ),
}
