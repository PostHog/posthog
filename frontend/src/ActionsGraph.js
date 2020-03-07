import React, { Component } from 'react'
import LineGraph from './LineGraph';
import api from './Api';
import { toParams, fromParams, Loading, Card, CloseButton, selectStyle } from './utils';
import { Dropdown } from "./Dropdown";
import { Link } from 'react-router-dom';
import PropTypes from 'prop-types';
import Select from 'react-select';
import SaveToDashboard from './SaveToDashboard';
import PropertyFilters from './PropertyFilter';
import moment from 'moment';
import DateFilter from './DateFilter';


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
        return data ? (data[0].labels ? <div style={{position: 'absolute', width: '100%', height: '100%'}}>
            <h1 style={{position: 'absolute', margin: '0 auto', left: '50%', top: '50%', fontSize: '3rem'}}><div style={{marginLeft: '-50%', marginTop: -30}}>{total}</div></h1>
            <LineGraph
            type='doughnut'
            datasets={data}
            labels={data[0].labels}
            />
        </div>: <p style={{textAlign: 'center', marginTop: '4rem'}}>We couldn't find any matching actions.</p>) : <Loading />;

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
            this.setState({data})
            this.props.onData && this.props.onData(data)
        })
    }
    componentDidUpdate(prevProps) {
        if(prevProps.filters !== this.props.filters) this.fetchGraph();
    }
    render() {
        let { data } = this.state;
        return data ? (data[0].labels ? <LineGraph
                            datasets={data}
                            labels={data[0].labels}
                            /> : <p style={{textAlign: 'center', marginTop: '4rem'}}>We couldn't find any matching actions.</p>) : <Loading />;
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
            this.setState({data})
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
        return data ? (data[0].labels ? <table className='table'>
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
        </table> : <p style={{textAlign: 'center', marginTop: '4rem'}}>We couldn't find any matching actions.</p>) : <Loading />;
    }
}
ActionsTable.propTypes = {
    filters: PropTypes.object.isRequired,
    onData: PropTypes.func
}

class BreakdownFilter extends Component {
    render() {
        return <div style={{width: 200, display: 'inline-block'}}>
            <Select
                cacheOptions
                defaultOptions
                style={{width: 200}}
                placeholder={"Break down by"}
                value={this.props.breakdown ? {label: this.props.breakdown, value: this.props.breakdown} : null}
                onChange={(item) => this.props.onChange(item.value)}
                styles={selectStyle}
                options={this.props.properties} />
        </div>
    }
}

class ActionFilter extends Component {
    constructor(props) {
        super(props)
        this.state = {
            actionFilters: props.actionFilters
        }
        this.Row = this.Row.bind(this);
        this.Math = this.Math.bind(this);
    }
    onMathSelect(index, math) {
        let { actionFilters } = this.state;
        actionFilters[index].math = math;
        this.props.onChange(actionFilters);
    }
    Math(props) {
        let items = ['Total', 'DAU']
        return <Dropdown title={items[items.map(i => i.toLowerCase()).indexOf(props.math)] || 'Total'} buttonClassName='btn btn-sm btn-light' style={{marginLeft: 32, marginRight: 16}}>
            <a href='#' className='dropdown-item' onClick={() => this.onMathSelect.call(this, props.index, 'total')}>Total</a>
            <a href='#' className='dropdown-item' onClick={() => this.onMathSelect.call(this, props.index, 'dau')}>DAU</a>
        </Dropdown>
    }
    Row(props) {
        let { selected, actionFilters } = this.state;
        let { actions } = this.props;
        let { action, filter, index } = props;
        return <div>
            <button className='filter-action' onClick={() => this.setState({selected: action.id})} style={{border: 0, padding: 0, fontWeight: 500, borderBottom: '1.5px dotted var(--blue)'}}>
                {action.name || 'Select action'}
            </button>
            <this.Math math={filter.math} index={index} />
            <CloseButton onClick={() => {
                actionFilters.splice(action.index, 1);
                this.props.onChange(actionFilters)
            }} style={{float: 'none', marginLeft: 8, position: 'absolute', marginTop: 3}} />
            {(!action.id, selected == action.id) && <div className='select-box'>
                {action.id && <a href={'/action/' + action.id} target="_blank">Edit "{action.name}" <i className='fi flaticon-export' /></a>}
                <Select
                    onBlur={(e) => {
                        if(e.relatedTarget && e.relatedTarget.tagName == 'A') return;
                        this.setState({selected: false})}}
                    onChange={(item) => {
                        actionFilters[index] = {id: item.value};
                        this.props.onChange(actionFilters)
                        this.setState({selected: false})
                    }}
                    defaultMenuIsOpen={true}
                    autoFocus={true}
                    styles={selectStyle}
                    options={actions.map(action => ({label: action.name, value: action.id}))} />
            </div>}
        </div>
    }
    componentDidUpdate(prevProps) { 
        if(prevProps.actionFilters != this.props.actionFilters) this.setState({actionFilters: this.props.actionFilters})
    }
    render() {
        let { actions } = this.props;
        let { actionFilters } = this.state;
        return actions ? <div>
            {actionFilters && actionFilters.map((action_filter, index) => {
                let action = actions.filter(action => action.id == action_filter.id)[0] || {};
                return <this.Row action={action} filter={action_filter} key={index} index={index} />
            })}
            <button className='btn btn-sm btn-outline-success' onClick={() => this.setState({actionFilters: [...actionFilters, {id: null}]})}>Add action</button>
        </div> : null;
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
        filters.actions = filters.actions && JSON.parse(filters.actions);
        filters.actions = Array.isArray(filters.actions) ? filters.actions : undefined;
        if(filters.breakdown) filters.display = 'ActionsTable';
        this.state = {filters};
        this.setDate = this.setDate.bind(this);

        this.fetchProperties.call(this)
        this.fetchActions.call(this);
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
    fetchActions() {
        api.get('api/action').then(actions => {
            if(!this.state.filters.actions) this.setFilters({actions: [{id: actions.results[actions.results.length - 1].id}]});
            this.setState({actions: actions.results})
        })
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
            search: toParams({...filters, actions: JSON.stringify(filters.actions)})
        })
        this.setState({
            filters,
            loading: true
        })
    }
    getPropertyFilters(filters) {
        let data = {};
        let nonPropKeys = ['date_from', 'date_to', 'actions', 'display', 'breakdown'];
        Object.keys(filters).map((key) => {
            if(nonPropKeys.indexOf(key) === -1) data[key] = filters[key]
        })
        return data;
    }
    setDate(date_from, date_to) {
        this.setFilters({date_from: date_from, date_to: date_to && date_to})
    }
    render() {
        let { actions, filters, properties } = this.state;
        let displayMap = {
            'ActionsLineGraph': 'Line chart',
            'ActionsTable': 'Table',
            'ActionsPie': 'Pie',
        }
        return (
            <div className='actions-graph'>
                <h1>Action trends</h1>
                <Card>
                    <div className='card-body'>
                        <h4 className='secondary'>Actions</h4>
                        <ActionFilter actions={actions} actionFilters={filters.actions} onChange={(actions) => this.setFilters({actions})} />
                        <hr />
                        <h4 className='secondary'>Filters</h4>
                        <PropertyFilters properties={properties} prefetchProperties={true} propertyFilters={this.getPropertyFilters(filters)} onChange={(propertyFilters) => this.setFilters({...propertyFilters})} style={{marginBottom: 0}} />
                        <hr />
                        <h4 className='secondary'>Break down by</h4>
                        <div style={{width: 230}}>
                            <BreakdownFilter properties={properties} breakdown={filters.breakdown} onChange={(breakdown) => this.setFilters({breakdown})} />
                            {filters.breakdown && <CloseButton onClick={() => this.setFilters({breakdown: false})} style={{marginTop: 1}} />}
                        </div>
                    </div>
                </Card>
                <Card
                    title={<span>
                        Graph
                        <div className='float-right'>
                            <Dropdown title={displayMap[filters.display || 'ActionsLineGraph']} buttonClassName='btn btn-sm btn-light' buttonStyle={{margin: '0 8px'}}>
                                <a className={'dropdown-item ' + (filters.breakdown && 'disabled')} href='#' onClick={(e) => this.setFilters({display: 'ActionsLineGraph'})}>Line chart {filters.breakdown && '(Not available with breakdown)'}</a>
                                <a className='dropdown-item' href='#' onClick={(e) => this.setFilters({display: 'ActionsTable'})}>Table</a>
                                <a className={'dropdown-item ' + (filters.breakdown && 'disabled')} href='#' onClick={(e) => this.setFilters({display: 'ActionsPie'})}>Pie {filters.breakdown && '(Not available with breakdown)'}</a>
                            </Dropdown>
                            <DateFilter onChange={this.setDate} dateFrom={filters.date_from} dateTo={filters.date_to} />
                            <SaveToDashboard filters={filters} type={filters.display || 'ActionsLineGraph'} />
                        </div>
                    </span>}>
                    <div className='card-body card-body-graph'>
                        {filters.actions && <div style={{minHeight: 'calc(70vh - 50px)', position: 'relative'}}>
                            {this.state.loading && <div className='loading-overlay'><div></div></div>}
                            {(!filters.display || filters.display == 'ActionsLineGraph') && <ActionsLineGraph filters={filters} onData={(data) => this.setState({data, loading: false})} />}
                            {filters.display == 'ActionsTable' && <ActionsTable filters={filters} onData={(data) => this.setState({data, loading: false})} />}
                            {filters.display == 'ActionsPie' && <ActionsPie filters={filters} onData={(data) => this.setState({data, loading: false})} />}
                        </div>}
                    </div>
                </Card>
            </div>
        )
    }
}