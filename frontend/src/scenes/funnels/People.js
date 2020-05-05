import React from 'react'
import { useValues } from 'kea'
import { funnelLogic } from './funnelLogic'
import { Link } from 'lib/components/Link'
import { Card, percentage, Loading } from 'lib/utils'

export function People({ id }) {
    const { stepsWithCount, peopleSorted, peopleLoading } = useValues(funnelLogic({ id }))

    return (
        <Card title="Per user">
            {peopleLoading && <Loading />}
            <table className="table table-bordered table-fixed">
                <tbody>
                    <tr>
                        <td></td>
                        {stepsWithCount &&
                            stepsWithCount.map(step => (
                                <th key={step.id}>
                                    <Link to={'/action/' + step.action_id}>{step.name}</Link>
                                </th>
                            ))}
                    </tr>
                    <tr>
                        <td></td>
                        {stepsWithCount &&
                            stepsWithCount.map(step => (
                                <td key={step.id}>
                                    {step.count}&nbsp; ({percentage(step.count / stepsWithCount[0].count)})
                                </td>
                            ))}
                    </tr>
                    {peopleSorted &&
                        peopleSorted.map(person => (
                            <tr key={person.id}>
                                <td className="text-overflow">
                                    <Link to={'/person_by_id/' + person.id}>{person.name}</Link>
                                </td>
                                {stepsWithCount.map(step => (
                                    <td
                                        key={step.id}
                                        className={
                                            step.people.indexOf(person.id) > -1 ? 'funnel-success' : 'funnel-dropped'
                                        }
                                    ></td>
                                ))}
                            </tr>
                        ))}
                </tbody>
            </table>
        </Card>
    )
}
