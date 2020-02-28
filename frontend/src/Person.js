import React, { Component } from 'react'
import { EventsTable } from './Events';
import api from './Api';

export default class Person extends Component {
    constructor(props) {
        super(props)
    
        this.state = {}
        this.fetchPerson.call(this);
        this.Value = this.Value.bind(this);
    }
    fetchPerson() {
        let url = '';
        if(this.props.match.params.distinct_id) {
            url = 'api/person/by_distinct_id/?distinct_id=' + this.props.match.params.distinct_id;
        } else {
            url = 'api/person/' + this.props.match.params.id;
        }
        api.get(url).then((person) => this.setState({person}))
    }
    Value(props) {
        let value = props.value;
        if(Array.isArray(value)) return <div>
            {value.map(item => <span><this.Value value={item} /><br /></span>)}
        </div>;
        if(value instanceof Object) return <table className='table'>
            <tbody>
                {Object.entries(value).map(([key, value]) => <tr>
                    <th>{key}</th><td><this.Value value={value} /></td>
                </tr>)}
            </tbody>
        </table>
        return value;
    }
    render() {
        return this.state.person ? <div>
            <h1>{this.state.person.name}</h1>
            <div style={{maxWidth: 750}}>
                <this.Value value={this.state.person.properties} />
                <table className='table'>
                    <tbody>
                        <tr>
                            <td>Distinct IDs</td>
                            <td>{this.state.person.distinct_ids.map((distinct_id) => <pre style={{margin: 0}}>{distinct_id}</pre>)}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <EventsTable fixedFilters={{person_id: this.state.person.id}} history={this.props.history} />
        </div>
        : null;
    }
}
