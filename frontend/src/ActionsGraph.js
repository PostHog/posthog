import React, { Component } from 'react'
import LineGraph from './LineGraph';
import api from './Api';

export default class ActionsGraph extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            selected: []
        }
        this.fetchGraph = this.fetchGraph.bind(this);
        this.fetchGraph()
    }
    fetchGraph(days) {
        api.get('api/action/trends' + (days ? '/?days=' + days : '')).then((data) => this.setState({
            data, 
            selected: data.map((item) => item.label)
        }))
    }

    render() {
        let { selected, data } = this.state;
        return (
            <div>
                <h1>Action trends</h1>
                <div>
                    <select
                        className='float-right form-control'
                        style={{width: 170}}
                        onChange={e => this.fetchGraph(e.target.value)}>
                        <option value="7">Show last 7 days</option>
                        <option value="14">Show last 14 days</option>
                        <option value="30">Show last 30 days</option>
                        <option value="60">Show last 60 days</option>
                        <option value="90">Show last 90 days</option>
                    </select>
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
                {data && <LineGraph
                    datasets={data.filter(item => selected.indexOf(item.label) > -1)}
                    labels={data[0].labels}
                    options={{}} />}
            </div>
        )
    }
}
