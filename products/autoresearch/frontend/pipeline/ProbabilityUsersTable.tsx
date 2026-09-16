import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'

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

/** Top/bottom-N users by predicted probability for a pipeline, grouped by person. */
export function ProbabilityUsersTable({
    pipelineId,
    direction,
}: {
    pipelineId: string
    direction: 'DESC' | 'ASC'
}): JSX.Element {
    return (
        <Query
            readOnly
            context={{
                columns: {
                    person: { title: 'Person', render: PersonCell },
                    probability: { title: 'Probability', render: PercentCell },
                    last_scored: { title: 'Last scored' },
                },
            }}
            query={{
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        WITH latest AS (
                            SELECT max(toDate(timestamp)) AS d
                            FROM events
                            WHERE event = 'autoresearch_prediction'
                              AND properties.$autoresearch_pipeline_id = {pipeline_id}
                        ),
                        scored AS (
                            SELECT
                                coalesce(nullIf(properties.$autoresearch_person_id, ''), distinct_id) AS person_id,
                                round(100 * argMax(toFloat(properties.$autoresearch_p_y), timestamp), 1) AS probability,
                                max(timestamp) AS last_scored
                            FROM events
                            WHERE event = 'autoresearch_prediction'
                              AND properties.$autoresearch_pipeline_id = {pipeline_id}
                              AND toDate(timestamp) = (SELECT d FROM latest)
                            GROUP BY person_id
                        )
                        -- LEFT JOIN persons directly on the person UUID: the implicit person join goes via
                        -- distinct_id, which drops scored people whose prediction events aren't person-mapped.
                        SELECT
                            tuple(s.person_id, coalesce(
                                nullIf(toString(p.properties.email), ''),
                                nullIf(toString(p.properties.name), '')
                            )) AS person,
                            s.probability AS probability,
                            s.last_scored AS last_scored
                        FROM scored s
                        LEFT JOIN persons p ON toString(p.id) = s.person_id
                        ORDER BY probability ${direction}
                        LIMIT 50
                    `,
                    values: { pipeline_id: pipelineId },
                },
            }}
        />
    )
}
