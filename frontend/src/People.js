import React, { Component } from 'react'
import api from './Api';
import { Link } from 'react-router-dom';
import moment from 'moment';
import { Card, fromParams, CloseButton } from './utils';
import PropertyFilters from './PropertyFilter';
import Select from 'react-select'
import { toast } from 'react-toastify';

let toParams = (obj) => Object.entries(obj).map(([key, val]) => `${key}=${encodeURIComponent(val)}`).join('&')

class CohortGroup extends Component {
    constructor(props) {
        super(props)
        this.state = {
            days: 1,
            selected: (props.group.action_id && 'action') || (props.group.properties && 'property')
        }
        this.DayChoice = this.DayChoice.bind(this);
    }
    DayChoice(props) {
        return <button
            onClick={() => this.props.onChange({action_id: this.props.group.action_id, days: props.days})}
            type="button"
            className={'btn btn-sm ' + (this.props.group.days == props.days ? 'btn-secondary' : 'btn-light')}>
                {props.name}
            </button>
    }
    render() {
        let { group, index, properties, actions, onChange, onRemove } = this.props;
        let { selected } = this.state;
        return <Card title={false} style={{margin: 0}}>
            <div className='card-body'>
                {index > 0 && <CloseButton className='float-right' onClick={onRemove} />}
                <div style={{height: 32}}>
                    User has
                    {selected == 'action' && ' done '}
                    <div className='btn-group' style={{margin: '0 8px'}}>
                        <button onClick={() => this.setState({selected: 'action'})} type="button" className={'btn btn-sm ' + (selected == 'action' ? 'btn-secondary' : 'btn-light')}>action</button>
                        <button onClick={() => this.setState({selected: 'property'})} type="button" className={'btn btn-sm ' + (selected == 'property' ? 'btn-secondary' : 'btn-light')}>property</button>
                    </div>
                    {selected == 'action' && <span>
                        in the last
                        <div className='btn-group' style={{margin: '0 8px'}}>
                            <this.DayChoice days={1} name='day' />
                            <this.DayChoice days={7} name='7 days' />
                            <this.DayChoice days={30} name='month' />
                        </div>
                    </span>}
                </div>
                {selected && <div style={{marginLeft: '2rem', minHeight: 38}}>
                    {selected == 'property' && <PropertyFilters
                        endpoint='person'
                        className=' '
                        onChange={properties => onChange({properties: properties, days: group.days})}
                        properties={properties}
                        propertyFilters={group.properties || {}}
                        style={{margin: '1rem 0 0'}}
                    />} 
                    {selected == 'action' && <div style={{marginTop: '1rem', width: 350}}>
                        <Select
                            options={actions}
                            placeholder="Select action..."
                            onChange={item => onChange({action_id: item.value})}
                            value={actions && actions.filter((action) => action.value == group.action_id)}
                            />
                    </div>}
                </div>}
            </div>
        </Card>
    }
}

class Cohort extends Component {
    constructor(props) {
        super(props)
        this.state = {
            groups: window.location.search.indexOf('new_cohort') > -1 ? [{}] : [],
            id: fromParams()['cohort']
        }
        this.fetchProperties.call(this);
        this.fetchActions.call(this);
        this.onSave = this.onSave.bind(this);
        if(this.state.id) this.fetchCohort.call(this);
    }
    fetchCohort() {
        api.get('api/cohort/' + this.state.id).then(cohort => this.setState(cohort))
    }
    onSave(e) {
        e.preventDefault();
        let cohort = {
            id: this.state.id, name: this.state.name, groups: this.state.groups
        }
        let onResponse = cohort => {
            this.props.onChange(cohort.id);
            this.setState({id: cohort.id})
            toast('Cohort saved.')
            this.props.history.push({
                pathname: this.props.history.location.pathname,
                search: toParams({cohort: cohort.id})
            })
        }
        if(this.state.id) {
            return api.update('api/cohort/' + this.state.id, cohort).then(onResponse)
        }
        api.create('api/cohort', cohort).then(onResponse)
    }
    fetchProperties() {
        api.get('api/person/properties').then((properties) => {
            this.setState({
                properties: properties.map((property) => (
                    {label: property.name, value: property.name}
                ))
            })
        });
    }
    fetchActions() {
        api.get('api/action').then((actions) => {
            this.setState({
                actions: actions.results.map((action) => (
                    {label: action.name, value: action.id}
                ))
            })
        });
    }
    render() {
        let { groups, properties, actions, name } = this.state;
        return groups.length == 0 ?
            <button
                className='btn btn-sm btn-outline-success float-right'
                style={{marginBottom: '1rem'}}
                onClick={() => this.setState({groups: [{}]})}>
                + new cohort
            </button> :
            <div style={{maxWidth: 750}}>
                <Card title={<span>
                    <CloseButton
                        className='float-right'
                        onClick={() => {
                            this.setState({groups: [], id: false})
                            this.props.onChange();
                            this.props.history.push({ pathname: this.props.history.location.pathname, search: {}})
                        }} />
                    {name || 'New cohort'}
                    </span>}>
                    <form className='card-body' onSubmit={this.onSave}>
                        <input style={{marginBottom: '1rem'}} required className='form-control' autoFocus placeholder='Cohort name...' value={name} onChange={e => this.setState({name: e.target.value})}/>
                        {groups.map((group, index) => <CohortGroup
                            key={index}
                            group={group}
                            properties={properties}
                            actions={actions}
                            index={index}
                            onRemove={() => {
                                groups.splice(index, 1);
                                this.setState({groups})
                            }}
                            onChange={group => {
                                groups[index] = group;
                                this.setState({groups})
                            }}
                            />).reduce((prev, curr) => [
                                prev,
                                <div style={{textAlign: 'center', fontSize: 13, letterSpacing: 1, opacity: 0.7, margin: 8}}> OR </div>,
                                curr
                            ])}
                        <button className='btn btn-outline-success btn-sm' style={{marginTop: '1rem'}} type="button" onClick={() => this.setState({groups: [...groups, {}]})}>New group</button>
                        <button className='btn btn-success btn-sm float-right' style={{marginTop: '1rem'}}>Save cohort</button>
                    </form>
                </Card>
            </div>
    }
}

export default class People extends Component {
    constructor(props) {
        super(props)
    
        this.state = {loading: true}
        this.FilterLink = this.FilterLink.bind(this);
        this.fetchPeople = this.fetchPeople.bind(this);
        this.fetchPeople(undefined, fromParams()['cohort']);
        this.clickNext = this.clickNext.bind(this);
    }
    fetchPeople(search, cohort_id) {
        if(search !== undefined) this.setState({loading: true});
        api.get('api/person/?include_last_event=1&' + (!!search ? 'search=' + search : '') + (cohort_id ? 'cohort=' + cohort_id : '')).then((data) => this.setState({people: data.results, hasNext: data.next, loading: false}))
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
        this.setState({hasNext: false, loading: true})
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
                <Cohort onChange={cohort_id => this.fetchPeople(false, cohort_id)} history={this.props.history} />
                {people && <input
                    className='form-control'
                    name='search'
                    autoFocus
                    onKeyDown={(e) => e.keyCode == "13" && this.fetchPeople(e.target.value)}
                    placeholder={people && "Try " + exampleEmail + " or has:email"} />}<br />
                <table className='table' style={{position: 'relative'}}>
                    {loading && <div className='loading-overlay'><div></div></div>}
                    <tbody>
                        <tr><th>Person</th><th>Last seen</th></tr>
                        {people && people.length == 0 && <tr><td colSpan="2">We haven't seen any data yet. If you haven't integrated PostHog, <Link to='/setup'>click here to set PostHog up on your app</Link></td></tr>}
                        {people && people.map((person) => [
                            <tr key={person.id} className='cursor-pointer' onClick={() => this.setState({personSelected: person.id})}>
                                <td><Link to={'/person/' + person.distinct_ids[0]} className='ph-no-capture'>{person.name}</Link></td>
                                <td>{person.last_event && moment(person.last_event.timestamp).fromNow()}</td>
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
