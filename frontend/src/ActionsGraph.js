import React, { Component } from 'react'
import LineGraph from './LineGraph';
import api from './Api';
import { Link } from 'react-router-dom';
import PropertyFilter from './PropertyFilter';
import { toParams, fromParams } from './utils';

export default class ActionsGraph extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            selected: []
        }
        let filters = fromParams()
        this.state.daysFilter = filters.days;
        delete filters.days;
        this.state.selected = filters.actions ? filters.actions.split(',').map((id) => parseInt(id)) : []
        delete filters.actions;
        this.state.propertyFilters = {...filters};

        this.fetchGraph = this.fetchGraph.bind(this);
        this.fetchGraph(this.state)
    }
    fetchGraph(setState) {
        let state = {...this.state, ...setState}
        let filters = {
            ...state.propertyFilters,
            ...(state.daysFilter ? {'days': state.daysFilter} : {}),
            actions: state.selected.join(',')
        }
        this.props.history.push({
            pathname: this.props.history.location.pathname,
            search: toParams(filters)
        })
        if(Object.keys(setState).length == 1 && setState.selected) return this.setState({...state}); // no need to call as action filtering happens in the frontend
        api.get('api/action/trends/?' + toParams(filters)).then((data) => this.setState({
            ...state,
            data: data.sort((a, b) => b.count - a.count),
            ...(!state.selected ? {selected: data.map((item) => item.action.id)} : {})
        }))
    }
    render() {
        let { selected, data, propertyFilters, daysFilter } = this.state;
        return (
            <div>
                <h1>Action trends</h1>
                <PropertyFilter propertyFilters={propertyFilters} onChange={(propertyFilters) => this.fetchGraph({propertyFilters})} history={this.props.history} />
                {data && data[0] && <select
                    className='float-right form-control'
                    style={{width: 170}}
                    value={daysFilter}
                    onChange={e => {
                        this.fetchGraph({daysFilter: e.target.value});
                    }}>
                    <option value="7">Show last 7 days</option>
                    <option value="14">Show last 14 days</option>
                    <option value="30">Show last 30 days</option>
                    <option value="60">Show last 60 days</option>
                    <option value="90">Show last 90 days</option>
                </select>}
                <br /><br /><br />
                <div className='row'>
                    <div className='col-10'>
                        {data && !data[0] && <p>You don't have any actions configured yet. <Link to='/actions'>Click here to create some.</Link></p>}
                        {data && data[0] && <LineGraph
                            datasets={data.filter((item) => selected.indexOf(item.action.id) > -1)}
                            labels={data[0].labels}
                            options={{}} />}
                    </div>
                    <div className='col-2'>
                        <strong>Actions</strong><br />
                        <small>
                            <a href='#' onClick={(e) => {e.preventDefault(); this.fetchGraph({selected: []})}}>Unselect all</a> /&nbsp;
                            <a href='#' onClick={(e) => {e.preventDefault(); this.fetchGraph({selected: data.map((item) => item.action.id)})}}>Select all</a>
                        </small><br />
                        {data && data.map((item) => <label className='cursor-pointer' style={{marginRight: 8, display: 'block', color: item.count > 0 ? 'inherit' : 'var(--gray)'}} key={item.label}>
                            <input
                                checked={selected.indexOf(item.action.id) > -1}
                                onChange={(e) => {
                                    if(e.target.checked) {
                                        selected.push(item.action.id);
                                    } else {
                                        selected = selected.filter((i) => i != item.action.id)
                                    }
                                    this.fetchGraph({selected})
                                }}
                                type='checkbox' /> {item.action.name} ({item.count})
                        </label>)}
                    </div>
                </div>
            </div>
        )
    }
}
