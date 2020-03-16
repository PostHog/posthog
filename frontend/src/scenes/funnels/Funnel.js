import React, { Component } from 'react'
import api from '../../lib/api'
import { Card, percentage, Loading } from '../../lib/utils'
import { Link } from 'react-router-dom'
import { SaveToDashboard } from '../../lib/components/SaveToDashboard'
import { EditFunnel } from './EditFunnel'
import { FunnelViz } from './FunnelViz'

export class Funnel extends Component {
    constructor(props) {
        super(props)

        this.state = {
            loadingFunnel: true,
            loadingPeople: true,
            steps: []
        }
        this.fetchFunnel()
        this.fetchFunnelFast()
    }
    sortPeople = people => {
        let score = person => {
            return this.state.steps.reduce(
                (val, step) =>
                    step.people.indexOf(person.id) > -1 ? val + 1 : val,
                0
            )
        }
        people.sort((a, b) => score(b) - score(a))
        return people
    }
    fetchFunnelFast = () => {
        api.get(
            'api/funnel/' + this.props.match.params.id + '/?exclude_count=1'
        ).then(funnel => this.setState({ funnel }))
    }
    fetchFunnel = () => {
        let now = new Date()
        this.currentFunnelFetch = now
        this.setState({ loadingFunnel: true, loadingPeople: true })
        api.get('api/funnel/' + this.props.match.params.id).then(funnel => {
            if (now != this.currentFunnelFetch) return
            this.setState({ steps: funnel.steps, loadingFunnel: false })
            if (!funnel.steps[0]) return
            api.get(
                'api/person/?id=' +
                    funnel.steps[0].people.slice(0, 99).join(',')
            ).then(people => {
                if (now != this.currentFunnelFetch) return
                this.setState({
                    people: this.sortPeople(people.results),
                    loadingPeople: false,
                })
            })
        })
    }
    render() {
        let { funnel, steps, people, loadingFunnel, loadingPeople } = this.state
        return funnel ? (
            <div className="funnel">
                <h1>Funnel: {funnel.name}</h1>
                <EditFunnel
                    funnelId={this.props.match.params.id}
                    onChange={funnel => this.fetchFunnel()}
                />
                <Card
                    title={
                        <span>
                            <SaveToDashboard
                                className="float-right"
                                filters={{ funnel_id: funnel.id }}
                                type="FunnelViz"
                                name={funnel.name}
                            />
                            Graph
                        </span>
                    }
                >
                    <div style={{ height: 300 }}>
                        {loadingFunnel && <Loading />}
                        {steps[0] && steps[0].count > -1 && (
                            <FunnelViz funnel={{steps}} />
                        )}
                    </div>
                </Card>
                <Card title="Per user">
                    {loadingPeople && <Loading />}
                    <table className="table table-bordered table-fixed">
                        <tbody>
                            <tr>
                                <td></td>
                                {steps.map(step => (
                                    <th key={step.id}>
                                        <Link to={'/action/' + step.action_id}>
                                            {step.name}
                                        </Link>
                                    </th>
                                ))}
                            </tr>
                            <tr>
                                <td></td>
                                {steps.map(step => (
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
                                people.map(person => (
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
                                                    step.people.indexOf(
                                                        person.id
                                                    ) > -1
                                                        ? 'funnel-success'
                                                        : 'funnel-dropped'
                                                }
                                            ></td>
                                        ))}
                                    </tr>
                                ))}
                        </tbody>
                    </table>
                </Card>
            </div>
        ) : (
            <Loading />
        )
    }
}
