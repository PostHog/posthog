import { LiveModelCard } from './LiveModelCard'
import { SuggestionsTab } from './SuggestionsTab'
import { TrainingTab } from './TrainingTab'

/** What the agent did (live model, training runs) next to how to steer it (suggestions). */
export function AgentResearchTab(): JSX.Element {
    return (
        <div className="space-y-4">
            <LiveModelCard />
            <div className="@container">
                <div className="grid grid-cols-1 @3xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-4 items-start">
                    <TrainingTab />
                    <SuggestionsTab />
                </div>
            </div>
        </div>
    )
}
