import React, { Component } from 'react'
import LineGraph from './LineGraph';
import api from './Api';
import { toParams, fromParams, Loading, Card } from './utils';
import { Link } from 'react-router-dom';
import PropTypes from 'prop-types';
import Select from 'react-select';
import SaveToDashboard from './SaveToDashboard';
import PropertyFilters from './PropertyFilter';


let colors = ['blue', 'yellow', 'green', 'red', 'purple', 'gray', 'indigo', 'pink', 'orange', 'teal', 'cyan', 'gray-dark'];
let getColorVar = (variable) => getComputedStyle(document.body).getPropertyValue('--' + variable)
export class ActionsPie extends Component {
    constructor(props) {
        super(props)
        this.state = {}
        this.fetchGraph = this.fetchGraph.bind(this);
        this.fetchGraph()
    }
    fetchGraph() {
        api.get('api/action/trends/?' + toParams(this.props.filters)).then((data) => {
            data = data.sort((a, b) => b.count - a.count)
            data = data
                    .filter((item) =>
                        this.props.filters.actions ? this.props.filters.actions.indexOf(item.action.id) > -1 : true
                    )
            let color_list = colors.map(color => getColorVar(color));
            this.setState({
                data: [{
                    labels: data.map(item => item.label),
                    data: data.map(item => item.data && item.data.reduce((prev, d) => prev + d, 0)),
                    backgroundColor: color_list,
                    hoverBackgroundColor: color_list,
                    hoverBorderColor: color_list,
                    borderColor: color_list,
                    hoverBorderWidth: 10,
                    borderWidth: 1
                }],
                total: data.reduce((prev, item) => prev + item.count, 0)
            })
            this.props.onData && this.props.onData(data)
        })
    }
    componentDidUpdate(prevProps) {
        if(prevProps.filters !== this.props.filters) this.fetchGraph();
    }
    render() {
        let { data, total } = this.state;
        return data ? (data[0] ? <div style={{position: 'absolute', width: '100%', height: '100%'}}>
            <h1 style={{position: 'absolute', margin: '0 auto', left: '50%', top: '50%', fontSize: '3rem'}}><div style={{marginLeft: '-50%', marginTop: -30}}>{total}</div></h1>
            <LineGraph
            type='doughnut'
            datasets={data}
            labels={data[0].labels}
            />
        </div>: <p>We couldn't find any matching elements</p>) : <Loading />;

    }
}

export class ActionsLineGraph extends Component {
    constructor(props) {
        super(props)
        this.state = {}
        this.fetchGraph = this.fetchGraph.bind(this);
        this.fetchGraph()
    }
    fetchGraph() {
        api.get('api/action/trends/?' + toParams(this.props.filters)).then((data) => {
            data = data.sort((a, b) => b.count - a.count)
            this.setState({data: data.filter((item) => this.props.filters.actions ? this.props.filters.actions.indexOf(item.action.id) > -1 : true)})
            this.props.onData && this.props.onData(data)
        })
    }
    componentDidUpdate(prevProps) {
        if(prevProps.filters !== this.props.filters) this.fetchGraph();
    }
    render() {
        let { data } = this.state;
        return data ? (data[0] ? <LineGraph
                            datasets={data}
                            labels={data[0].labels}
                            /> : <p>We couldn't find any matching elements</p>) : <Loading />;
    }
}

ActionsLineGraph.propTypes = {
    filters: PropTypes.object.isRequired,
    onData: PropTypes.func
}

export class ActionsTable extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
        this.fetchGraph = this.fetchGraph.bind(this);
        this.fetchGraph()
    }
    fetchGraph() {
        api.get('api/action/trends/?' + toParams(this.props.filters)).then((data) => {
            data = data.sort((a, b) => b.count - a.count)
            this.setState({data: data.filter((item) => this.props.filters.actions ? this.props.filters.actions.indexOf(item.action.id) > -1 : true)})
            this.props.onData && this.props.onData(data)
        })
    }
    componentDidUpdate(prevProps) {
        if(prevProps.filters !== this.props.filters) {
            this.fetchGraph();
        }
    }
    render() {
        let { data } = this.state;
        let { filters } = this.props;
        return data ? (data[0] ? <table className='table'>
            <tbody>
                <tr>
                    <th style={{width: 100}}>Action</th>
                    {filters.breakdown && <th>Breakdown</th>}
                    <th style={{width: 50}}>Count</th>
                </tr>
                {!filters.breakdown && data.map((item) => <tr key={item.label}>
                    <td>{item.label}</td>
                    <td>{item.count}</td>
                </tr>)}
                {filters.breakdown && data.filter((item) => item.count > 0).map((item) => [
                    <tr key={item.label}>
                        <td rowSpan={item.breakdown.length || 1}>{item.label}</td>
                        <td className='text-overflow'>{item.breakdown[0] && item.breakdown[0].name}</td>
                        <td>{item.breakdown[0] && item.breakdown[0].count}</td>
                    </tr>,
                    item.breakdown.slice(1).map((i) => <tr key={i.name}>
                        <td className='text-overflow'>{i.name}</td>
                        <td>{i.count}</td>
                    </tr>)
                ])}
            </tbody>
        </table> : <p>We couldn't find any matching elements</p>) : <Loading />;
    }
}
ActionsTable.propTypes = {
    filters: PropTypes.object.isRequired,
    onData: PropTypes.func
}

class BreakdownFilter extends Component {
    render() {
        return <div style={{width: 200}}>
            <Select
                cacheOptions
                defaultOptions
                style={{width: 200}}
                placeholder={"Break down by"}
                value={this.props.breakdown ? {label: this.props.breakdown, value: this.props.breakdown} : null}
                onChange={(item) => this.props.onChange(item.value)}
                options={this.props.properties} />
        </div>
    }
}

class ActionFilter extends Component {
    constructor(props) {
        super(props)
        this.state = {}
        this.Row = this.Row.bind(this);
        this.fetchActions.call(this);
    }
    fetchActions() {
        api.get('api/action').then(actions => this.setState({actions: actions.results}))
    }
    Row(props) {
        let { data, actionFilters } = this.props;
        let action = props.action;
        return <div>
            <label className='cursor-pointer filter-action' style={{marginRight: 8, display: 'block', color: props.count > 0 ? 'inherit' : 'var(--gray)'}} key={action.id}>
                <input
                    checked={actionFilters ? actionFilters.indexOf(action.id) > -1 : true}
                    onChange={(e) => {
                        if(e.target.checked) {
                            actionFilters.push(action.id);
                        } else {
                            if(!actionFilters) actionFilters = data.map((action) => action.id);
                            actionFilters = actionFilters.filter((i) => i != action.id);
                        }
                        this.props.onChange(actionFilters)
                    }}
                    type='checkbox' /> {action.name} {props.count > 0 && '(' + props.count + ')'}
                    <small className='filter-action-only'><a href='#' className='float-right' onClick={(e) => {e.preventDefault(); this.props.onChange([action.id])}}>only</a></small>
            </label>
        </div>
    }
    render() {
        let { data } = this.props;
        let { actions } = this.state;
        return <div>
            <small>
                <a href='#' onClick={(e) => {e.preventDefault(); this.props.onChange([])}}>Unselect all</a> /&nbsp;
                <a href='#' onClick={(e) => {e.preventDefault(); this.props.onChange(false)}}>Select all</a>
            </small><br />
            {data && data.map(item => <this.Row count={item.count} action={item.action} />)}
            {actions && data && actions
                .filter(action =>
                    data.filter(item => item.action.id == action.id).length == 0
                )
                .map(action => <this.Row action={action} />)}
        </div>
    }
}

export default class ActionsGraph extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            loading: true,
            properties: []
        }
        let filters = fromParams()
        filters.actions = filters.actions && filters.actions.split(',').map((id) => parseInt(id))
        if(filters.breakdown) filters.display = 'ActionsTable';
        this.state = {filters};

        this.fetchProperties.call(this)
    }
    fetchProperties() {
        api.get('api/event/properties').then((properties) =>
            this.setState({
                properties: properties.map((property) => (
                    {label: property.name, value: property.name}
                ))
            })
        )
    }
    setFilters(setState) {
        let filters = {
            days: this.state.filters.days,
            actions: this.state.filters.actions,
            display: this.state.filters.display,
            breakdown: this.state.filters.breakdown,
            ...setState
        }
        if(filters.breakdown) filters.display = 'ActionsTable';
        this.props.history.push({
            pathname: this.props.history.location.pathname,
            search: toParams({...filters, actions: filters.actions ? filters.actions.join(',') : false})
        })
        this.setState({
            filters,
            loading: true
        })
    }
    getPropertyFilters(filters) {
        let data = {};
        Object.keys(filters).map((key) => {
            if(key != 'days' && key != 'actions' && key != 'display' && key != 'breakdown') data[key] = filters[key]
        })
        return data;
    }
    render() {
        let { filters, data, properties } = this.state;
        return (
            <div className='actions-graph'>
                <h1>Action trends</h1>
                <PropertyFilters properties={properties} prefetchProperties={true} propertyFilters={this.getPropertyFilters(filters)} onChange={(propertyFilters) => this.setFilters({...propertyFilters})} />
                <select
                    className='float-right form-control'
                    style={{width: 170, marginLeft: 8}}
                    value={filters.days}
                    onChange={e => {
                        this.setFilters({days: e.target.value});
                    }}>
                    <option value="7">Show last 7 days</option>
                    <option value="14">Show last 14 days</option>
                    <option value="30">Show last 30 days</option>
                    <option value="60">Show last 60 days</option>
                    <option value="90">Show last 90 days</option>
                </select>
                <select
                    className='float-right form-control'
                    style={{width: 170}}
                    value={filters.display}
                    onChange={e => {
                        this.setFilters({display: e.target.value});
                    }}>
                    <option value="ActionsLineGraph" disabled={filters.breakdown}>Line chart {filters.breakdown && '(Not available with breakdown)'}</option>
                    <option value="ActionsTable">Table</option>
                    <option value="ActionsPie" disabled={filters.breakdown}>Pie {filters.breakdown && '(Not available with breakdown)'}</option>
                </select>
                <BreakdownFilter properties={properties} breakdown={filters.breakdown} onChange={(breakdown) => this.setFilters({breakdown})} />
                <br />
                <div className='row'>
                    <div className='col-10'>
                        <Card
                            title={<span><SaveToDashboard className='float-right' filters={filters} type={filters.display || 'ActionsLineGraph'} /> Graph</span>}>
                            <div className='card-body card-body-graph'>
                                <div style={{minHeight: 'calc(70vh - 50px)', position: 'relative'}}>
                                    {this.state.loading && <div className='loading-overlay'><div></div></div>}
                                    {(!filters.display || filters.display == 'ActionsLineGraph') && <ActionsLineGraph filters={filters} onData={(data) => this.setState({data, loading: false})} />}
                                    {filters.display == 'ActionsTable' && <ActionsTable filters={filters} onData={(data) => this.setState({data, loading: false})} />}
                                    {filters.display == 'ActionsPie' && <ActionsPie filters={filters} onData={(data) => this.setState({data, loading: false})} />}
                                </div>
                            </div>
                        </Card>
                    </div>
                    <div className='col-2'>
                        <Card title='Actions'>
                            <div className='card-body'>
                                <ActionFilter actionFilters={filters.actions} data={data} onChange={(actions) => this.setFilters({actions})} />
                            </div>
                        </Card>
                    </div>
                </div>
            </div>
        )
    }
}
