import { ExperimentDrawer } from './ExperimentDrawer'
import { StatusBrief } from './StatusBrief'
import { SteerAgentBar } from './SteerAgentBar'
import { TrainingTab } from './TrainingTab'

/** Where the live model stands, how to steer the next run, then what the agent did (search chart, run log). */
export function AgentResearchTab(): JSX.Element {
    return (
        <div className="@container space-y-4 min-w-0">
            <StatusBrief />
            <SteerAgentBar />
            <TrainingTab />
            <ExperimentDrawer />
        </div>
    )
}
