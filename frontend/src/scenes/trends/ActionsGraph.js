import React, { Component } from 'react'
import api from '../../lib/api';
import { toParams, fromParams, Card, CloseButton } from '../../lib/utils';
import { Dropdown } from "../../lib/components/Dropdown";
import { SaveToDashboard } from '../../lib/components/SaveToDashboard';
import { PropertyFilters } from '../../lib/components/PropertyFilters/PropertyFilters';
import { DateFilter } from '../../lib/components/DateFilter';
import { ActionFilter } from './ActionFilter';
import { ActionsPie } from './ActionsPie'
import { BreakdownFilter } from './BreakdownFilter'
import { ActionsTable } from './ActionsTable'
import { ActionsLineGraph } from './ActionsLineGraph'

export class ActionsGraph extends Component {
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
        filters.properties = filters.properties ? JSON.parse(filters.properties) : {};
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
            actions: this.state.filters.actions,
            display: this.state.filters.display,
            breakdown: this.state.filters.breakdown,
            date_from: this.state.filters.date_from,
            date_to: this.state.filters.date_to,
            properties: this.state.filters.properties,
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
                        <PropertyFilters properties={properties} prefetchProperties={true} propertyFilters={filters.properties} onChange={(properties) => this.setFilters({properties})} style={{marginBottom: 0}} />
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
