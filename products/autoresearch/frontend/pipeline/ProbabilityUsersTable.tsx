import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { PREDICTIONS_PEOPLE_VIEWS, predictionsPeopleQuery } from '../predictionsPeopleQuery'

/** Links to the person's page. The value is a (person UUID, display name) tuple; the display name falls back to the UUID. */
function PersonCell({ value }: { value: unknown }): JSX.Element {
    const [id, name] = Array.isArray(value) ? value : [value, null]
    const personId = id == null ? '' : String(id)
    if (!personId) {
        return <>—</>
    }
    const display = typeof name === 'string' && name ? name : personId
    return <Link to={urls.personByUUID(personId)}>{display}</Link>
}

function PercentCell({ value }: { value: unknown }): JSX.Element {
    return value == null ? <>—</> : <>{String(value)}%</>
}

function ChangeCell({ value }: { value: unknown }): JSX.Element {
    const change = Number(value)
    if (!change) {
        return <span className="text-muted">No change</span>
    }
    return (
        <span className={change > 0 ? 'text-success' : 'text-danger'}>
            {change > 0 ? '+' : ''}
            {change} pts
        </span>
    )
}

/** The top people of the latest scoring run, in the selected view. */
export function ProbabilityUsersTable({ pipelineId }: { pipelineId: string }): JSX.Element {
    const { predictionsPeopleView } = useValues(autoresearchPipelineLogic)
    const { setPredictionsPeopleView } = useActions(autoresearchPipelineLogic)

    return (
        <div className="space-y-2">
            <LemonSegmentedButton
                size="small"
                value={predictionsPeopleView}
                onChange={setPredictionsPeopleView}
                options={PREDICTIONS_PEOPLE_VIEWS.map(({ value, label }) => ({
                    value,
                    label,
                    'data-attr': `autoresearch-predictions-view-${value}`,
                }))}
            />
            <Query
                readOnly
                context={{
                    columns: {
                        person: { title: 'Person', render: PersonCell },
                        probability: { title: 'Probability', render: PercentCell },
                        change: { title: 'Change since last score', render: ChangeCell },
                        last_scored: { title: 'Last scored' },
                    },
                }}
                query={{
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query: predictionsPeopleQuery(predictionsPeopleView),
                        values: { pipeline_id: pipelineId },
                    },
                }}
            />
        </div>
    )
}
