import React, { Component } from 'react'
import api from './Api';
import { ActionsLineGraph, ActionsTable } from './ActionsGraph';
import { Link } from 'react-router-dom';
import { Dropdown, toParams, DeleteWithUndo } from './utils';
import { toast } from 'react-toastify';
import { FunnelViz } from './Funnel';

export default class Dashboard extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
        this.fetchDashboard = this.fetchDashboard.bind(this);
        this.fetchDashboard();
    }
    fetchDashboard() {
        api.get('api/dashboard').then((items) => this.setState({items: items.results}))
    }
    render() {
        let { items } = this.state;
        let typeMap = {
            'ActionsLineGraph': {
                element: ActionsLineGraph,
                link: filters => ({pathname: '/actions/trends', search: toParams(filters)})
            },
            'ActionsTable': {
                element: ActionsTable,
                link: filters => ({pathname: '/actions/trends', search: toParams(filters)})
            },
            'FunnelViz': {
                element: FunnelViz,
                link: filters => '/funnel/' + filters.funnel_id
            }
        }
        return (
            <div className='row'>
                {items && (items.length > 0 ? items.map((item) => {
                    let Panel = typeMap[item.type].element
                    return <div className='col-6' key={item.id}>
                        <div className='card'>
                            <h5 className='card-header'>
                                <Dropdown className='float-right'>
                                    <Link className='dropdown-item' to={typeMap[item.type].link(item.filters)}>View graph</Link>
                                    <DeleteWithUndo
                                        object={item}
                                        className='text-danger dropdown-item'
                                        endpoint='dashboard'
                                        callback={this.fetchDashboard}
                                        >Delete panel</DeleteWithUndo>
                                </Dropdown>
                                <Link to={typeMap[item.type].link(item.filters)}>{item.name}</Link>
                            </h5>
                            <div style={{overflowY: 'scroll', height: '25vh', maxHeight: '30vh'}}>
                                <Panel filters={item.filters} />
                            </div>
                        </div>
                    </div>
                }) : <p>You don't have any panels set up. <Link to='/actions/trends'>Click here to create one.</Link></p>)}
            </div>
        )
    }
}
