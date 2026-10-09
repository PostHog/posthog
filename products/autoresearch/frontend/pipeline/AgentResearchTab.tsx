import { AgentNotes } from './AgentNotes'
import { LiveModelCard } from './LiveModelCard'
import { SuggestionsTab } from './SuggestionsTab'
import { TrainingTab } from './TrainingTab'

/** What the agent did (search chart, experiment log) next to the live model, its notes, and how to steer it. */
export function AgentResearchTab(): JSX.Element {
    return (
        <div className="@container">
            <div className="grid grid-cols-1 @3xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-4 items-start">
                <TrainingTab />
                <div className="space-y-4 min-w-0">
                    <LiveModelCard />
                    <AgentNotes />
                    <SuggestionsTab />
                </div>
            </div>
        </div>
    )
}
