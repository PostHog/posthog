import React, { Component } from 'react'
import PropTypes from 'prop-types'
import Select from 'react-select'
import AsyncCreatableSelect from 'react-select/async-creatable'
import api from './Api';
import { toParams } from './utils';

export default class PropertyFilter extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            filters: []
        }
        this.Filter = this.Filter.bind(this);
        this.set = this.set.bind(this);
        this.loadPropertyValues = this.loadPropertyValues.bind(this);
        this.fetchProperties.call(this);
    }
    fetchProperties() {
        api.get('api/event/properties').then((properties) =>
            this.setState({
                properties: properties.map((property) => (
                    {label: property.name + ' (' + property.count + ')', value: property.name}
                ))
            })
        )
    }
    loadPropertyValues(key) {
        return (value, callback) => {
            api.get('api/event/values/?key=' + key + (value ? '&value=' + value : '')).then((propValues) => callback(
                propValues.map((property) => (
                    {label: property.name + ' (' + property.count + ')', value: property.name}
                ))
            ))
        }
    }
    set(index, key, value) {
        let filters = this.state.filters;
        filters[index][key] = value;
        this.setState({filters})
        if(key != 'value') return;
        let dict = {};
        filters.map((item) => dict[item.name] = item.value)
        this.props.onChange(dict)
    }
    Filter(props) {
        let { properties } = this.state;
        let { index, filter } = props;
        return <div className='row' style={{marginBottom: '1rem'}}>
            <div className='col'>
                <Select
                    options={properties}
                    style={{width: 200}}
                    value={properties.filter((property) => property.value == filter.name)[0]}
                    onChange={(item) => this.set(index, 'name', item.value)}
                    />
            </div>
            <div className='col'>
                {filter.name && <AsyncCreatableSelect
                    loadOptions={this.loadPropertyValues(filter.name)}
                    defaultOptions
                    formatCreateLabel={(inputValue) => inputValue}
                    key={filter.name} // forces a reload of the component when the property changes
                    style={{width: 200}}
                    onChange={(item) => this.set(index, 'value', item.value)}
                    />
                }
            </div>
        </div>
    }
    render() {
        let { filters, history } = this.state;
        return <div style={{marginBottom: '2rem'}}>
            {filters.map((filter, index) => <this.Filter key={index} index={index} filter={filter} />)}
            <button className='btn btn-sm btn-outline-success' onClick={() => this.setState({filters: [...filters, {}]})}>Add filter</button>
        </div>
    }
}

PropertyFilter.propTypes = {
    history: PropTypes.object.isRequired
}