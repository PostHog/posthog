/* DEPRECATED: We now use the PersonsModal.tsx to show person information for funnels.
    this component is still used for Postgres-based instances. */
import React from 'react'
import { useValues } from 'kea'
import { funnelLogic } from './funnelLogic'
import { Link } from 'lib/components/Link'
import { percentage, Loading } from 'lib/utils'
import { EntityTypes } from '~/types'
import './FunnelPeople.scss'
import { Card } from 'antd'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

export function People(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { stepsWithCount, peopleSorted, peopleLoading, areFiltersValid, aggregationTargetLabel } = useValues(
        funnelLogic(insightProps)
    )

    if (!stepsWithCount && !areFiltersValid) {
        return null
    }

    return (
        <Card title="Per user" className="funnel-people" style={{ marginTop: 16 }}>
            {peopleLoading ? (
                <Loading style={{ minHeight: 50 }} />
            ) : !peopleSorted || peopleSorted.length === 0 ? (
                <div style={{ textAlign: 'center', margin: '3rem 0' }}>
                    No {aggregationTargetLabel.plural} found for this funnel.
                </div>
            ) : (
                <table className="table-bordered full-width">
                    <tbody>
                        <tr>
                            <th />
                            {stepsWithCount.map((step, index) => (
                                <th key={index}>
                                    {step.type === EntityTypes.ACTIONS ? (
                                        <Link to={'/action/' + step.action_id}>{step.name}</Link>
                                    ) : (
                                        step.name
                                    )}
                                </th>
                            ))}
                        </tr>
                        <tr>
                            <td />
                            {stepsWithCount.map((step, index) => (
                                <td key={index}>
                                    {step.count}&nbsp;{' '}
                                    {step.count > 0 && (
                                        <span>({percentage(step.count / stepsWithCount[0].count)})</span>
                                    )}
                                </td>
                            ))}
                        </tr>
                        {peopleSorted.map((person) => (
                            <tr key={person.id} data-attr="funnel-person">
                                <td className="text-overflow">
                                    <Link to={urls.person(person.distinct_ids[0])}>{person.name}</Link>
                                </td>
                                {stepsWithCount.map((step, index) => (
                                    <td
                                        key={index}
                                        className={
                                            (step.people?.indexOf(person.uuid) ?? -1) > -1
                                                ? 'funnel-success'
                                                : 'funnel-dropped'
                                        }
                                    />
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </Card>
    )
}
