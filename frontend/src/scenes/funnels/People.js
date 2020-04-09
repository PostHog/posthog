import React from 'react'
import { useValues, useActions } from 'kea';
import { funnelLogic } from './funnelLogic';
import { Link } from 'react-router-dom'
import { Card, percentage, Loading } from '../../lib/utils'

const sortPeople = (steps, people) => {
    const score = person => {
        return steps.reduce(
            (val, step) =>
                step.people.indexOf(person.id) > -1 ? val + 1 : val,
            0
        )
    }
    return people.sort((a, b) => score(b) - score(a))
}

export function People({ match }) {
    const { steps, people, peopleLoading } = useValues(funnelLogic({id: match.params.id}));

    return <Card title="Per user">
            {peopleLoading && <Loading />}
            <table className="table table-bordered table-fixed">
                <tbody>
                    <tr>
                        <td></td>
                        {steps && steps.map(step => (
                            <th key={step.id}>
                                <Link to={'/action/' + step.action_id}>
                                    {step.name}
                                </Link>
                            </th>
                        ))}
                    </tr>
                    <tr>
                        <td></td>
                        {steps && steps.map(step => (
                            <td key={step.id}>
                                {step.count}&nbsp; (
                                {percentage(
                                    step.count / steps[0].count
                                )}
                                )
                            </td>
                        ))}
                    </tr>
                    {people &&
                        sortPeople(steps, people).map(person => (
                            <tr key={person.id}>
                                <td className="text-overflow">
                                    <Link
                                        to={
                                            '/person_by_id/' + person.id
                                        }
                                    >
                                        {person.name}
                                    </Link>
                                </td>
                                {steps.map(step => (
                                    <td
                                        key={step.id}
                                        className={
                                            step.people.indexOf(person.id) > -1 ? 'funnel-success' : 'funnel-dropped'
                                        }
                                    >
                                    </td>
                                ))}
                            </tr>
                        ))}
                </tbody>
            </table>
        </Card>
}