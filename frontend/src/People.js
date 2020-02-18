import React, { Component } from 'react'
import api from './Api';
import { Link } from 'react-router-dom';
import moment from 'moment';
import { debounce } from './utils';

let toParams = (obj) => Object.entries(obj).map(([key, val]) => `${key}=${encodeURIComponent(val)}`).join('&')
export default class People extends Component {
    constructor(props) {
        super(props)
    
        this.state = {loading: true}
        this.FilterLink = this.FilterLink.bind(this);
        this.fetchPeople = this.fetchPeople.bind(this);
        this.debounceFetchPeople = debounce(this.fetchPeople.bind(this), 250)
        this.fetchPeople();
        this.clickNext = this.clickNext.bind(this);
    }
    fetchPeople(search) {
        api.get('api/person/?include_last_event=1&' + (!!search ? 'search=' + search : '')).then((data) => this.setState({people: data.results, hasNext: data.next, loading: false}))
    }
    FilterLink(props) {
        let filters = {...this.state.filters};
        filters[props.property] = props.value;
        return <Link
            to={{pathname: this.props.history.pathname, search: toParams(filters)}}
            onClick={(event) => {
                this.state.filters[props.property] = props.value;
                this.setState({filters: this.state.filters});
                this.fetchEvents();
            }}
            >{typeof props.value === 'object' ? JSON.stringify(props.value) : props.value}</Link>
    }
    clickNext() {
        let { people, hasNext } = this.state;
        this.setState({hasNext: false})
        api.get(hasNext).then((olderPeople) => {
            this.setState({people: [...people, ...olderPeople.results], hasNext: olderPeople.next, loading: false})
        });
    }
    render() {
        let { hasNext, people, loading } = this.state;
        let exampleEmail = (people && people.map((person) => person.properties.email).filter((d) => d)[0]) || 'example@gmail.com';
        return (
            <div>
                <h1>Users</h1>
                {people && <input
                    className='form-control'
                    name='search'
                    autoFocus
                    onKeyDown={(e) => e.keyCode == "13" ? this.fetchPeople(e.target.value) : this.debounceFetchPeople(e.target.value)}
                    placeholder={people && "Try " + exampleEmail + " or has:email"} />}<br />
                <table className='table'>
                    {loading && <div className='loading-overlay'><div></div></div>}
                    <tbody>
                        <tr><th>Person</th><th>Last seen</th><th>First seen</th></tr>
                        {people && people.length == 0 && <tr><td colSpan="2">We haven't seen any data yet. If you haven't integrated PostHog, <Link to='/setup'>click here to set PostHog up on your app</Link></td></tr>}
                        {people && people.map((person) => [
                            <tr key={person.id} className='cursor-pointer' onClick={() => this.setState({personSelected: person.id})}>
                                <td><Link to={'/person/' + person.distinct_ids[0]}>{person.name}</Link></td>
                                <td>{person.last_event && moment(person.last_event.timestamp).fromNow()}</td>
                                <td title={person.created_at}>{moment(person.created_at).fromNow()}</td>
                            </tr>,
                            this.state.personSelected == person.id && <tr key={person.id + '_open'}>
                                <td colSpan="4">
                                    {Object.keys(person.properties).length == 0 && "This person has no properties."}
                                    <div className='d-flex flex-wrap flex-column' style={{height: 200}}>
                                        {Object.keys(person.properties).sort().map((key) => <div style={{flex: '0 1 '}} key={key}>
                                            <strong>{key}:</strong> <this.FilterLink property={key} value={person.properties[key]} />
                                        </div>)}
                                    </div>
                                </td>
                            </tr>
                        ])}
                    </tbody>
                </table>
                {people && people.length > 0 && <button className='btn btn-primary' onClick={this.clickNext} style={{margin: '2rem auto 15rem', display: 'block'}} disabled={!hasNext}>
                    Load more events
                </button>}
            </div>
        )
    }
}
