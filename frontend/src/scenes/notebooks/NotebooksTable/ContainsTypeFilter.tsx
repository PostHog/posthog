import posthog from 'posthog-js'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { NotebooksListFilters } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'

import { NotebookNodeType } from '../types'

export const fromNodeTypeToLabel: Omit<
    Record<NotebookNodeType, string>,
    | NotebookNodeType.Backlink
    | NotebookNodeType.PersonFeed
    | NotebookNodeType.PersonProperties
    | NotebookNodeType.GroupProperties
    | NotebookNodeType.Map
    | NotebookNodeType.Mention
    | NotebookNodeType.Embed
    | NotebookNodeType.Latex
> = {
    [NotebookNodeType.FeatureFlag]: 'Feature flags',
    [NotebookNodeType.FeatureFlagCodeExample]: 'Feature flag Code Examples',
    [NotebookNodeType.Experiment]: 'Experiments',
    [NotebookNodeType.EarlyAccessFeature]: 'Early Access Features',
    [NotebookNodeType.Survey]: 'Surveys',
    [NotebookNodeType.Image]: 'Images',
    [NotebookNodeType.Person]: 'Persons',
    [NotebookNodeType.Query]: 'Queries',
    [NotebookNodeType.Recording]: 'Session recordings',
    [NotebookNodeType.RecordingPlaylist]: 'Session replay playlists',
    [NotebookNodeType.ReplayTimestamp]: 'Session recording comments',
    [NotebookNodeType.Cohort]: 'Cohorts',
    [NotebookNodeType.Group]: 'Groups',
    [NotebookNodeType.TaskCreate]: 'Task suggestions',
    [NotebookNodeType.LLMTrace]: 'LLM traces',
    [NotebookNodeType.Issues]: 'Issues',
    [NotebookNodeType.UsageMetrics]: 'Usage metrics',
    [NotebookNodeType.ZendeskTickets]: 'Zendesk tickets',
    [NotebookNodeType.RelatedGroups]: 'Related groups',
}

export function ContainsTypeFilters({
    filters,
    setFilters,
}: {
    filters: NotebooksListFilters
    setFilters: (selection: Partial<NotebooksListFilters>) => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span>Containing:</span>
            <LemonInputSelect
                mode="multiple"
                placeholder="Any content"
                options={Object.entries(fromNodeTypeToLabel)
                    .filter((entry) => entry[1] !== '')
                    .map(([type, label]) => ({ key: type, label }))}
                value={filters.contains}
                onChange={(newValue: string[]) => {
                    posthog.capture('notebook containing filter applied')
                    setFilters({ contains: newValue.map((x) => x as NotebookNodeType) })
                }}
                data-attr="notebooks-list-contains-filters"
            />
        </div>
    )
}
