import React, { Component } from 'react'
import LineGraph from './LineGraph';
import api from './Api';
import { Link } from 'react-router-dom';
import PropertyFilter from './PropertyFilter';
import { toParams } from './utils';

export default class ActionsGraph extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            selected: [],
            propertyFilters: {}
        }
        this.fetchGraph = this.fetchGraph.bind(this);
        this.fetchGraph()
    }
    fetchGraph() {
        let filters = Object.assign(this.state.propertyFilters, this.state.daysFilter ? {'days': this.state.daysFilter} : {})
        api.get('api/action/trends/?' + toParams(filters)).then((data) => this.setState({
            data, 
            selected: data.map((item) => item.label)
        }))
    }
    render() {
        let { selected, data } = this.state;
        return (
            <div>
                <h1>Action trends</h1>
                <PropertyFilter onChange={(propertyFilters) => this.setState({propertyFilters}, this.fetchGraph)} history={this.props.history} />
                <div>
                    {data && data[0] && <select
                        className='float-right form-control'
                        style={{width: 170}}
                        onChange={e => {
                            this.setState({daysFilter: e.target.value}, this.fetchGraph)
                        }}>
                        <option value="7">Show last 7 days</option>
                        <option value="14">Show last 14 days</option>
                        <option value="30">Show last 30 days</option>
                        <option value="60">Show last 60 days</option>
                        <option value="90">Show last 90 days</option>
                    </select>}
                    {data && data.map((item) => <label className='cursor-pointer' style={{marginRight: 8}}>
                        <input
                            checked={selected.indexOf(item.label) > -1}
                            onChange={(e) => {
                                if(e.target.checked) {
                                    selected.push(item.label);
                                } else {
                                    selected = selected.filter((i) => i != item.label)
                                }
                                this.setState({selected})
                            }}
                            type='checkbox' /> {item.action.name} ({item.count})
                    </label>)}
                </div>
                {data && !data[0] && <p>You don't have any actions configured yet. <Link to='/actions'>Click here to create some.</Link></p>}
                {data && data[0] && <LineGraph
                    datasets={data.filter(item => selected.indexOf(item.label) > -1)}
                    labels={data[0].labels}
                    options={{}} />}
            </div>
        )
    }
}
