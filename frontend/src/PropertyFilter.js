import React, { Component } from 'react'
import PropTypes from 'prop-types'
import Select from 'react-select'
import AsyncCreatableSelect from 'react-select/async-creatable'
import api from './Api';
import { CloseButton } from './utils';

export class PropertyFilter extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
        this.loadPropertyValues = this.loadPropertyValues.bind(this);
    }
    loadPropertyValues(key) {
        return (value, callback) => {
            api.get('api/' + this.props.endpoint + '/values/?key=' + key + (value ? '&value=' + value : '')).then((propValues) => callback(
                propValues.map((property) => (
                    {label: property.name ? property.name : '(empty)', value: property.name}
                ))
            ))
        }
    }   
    render() {
        let { properties, index, filter, onSet, onRemove } = this.props;
        return <div className='row' style={{margin: '1rem -15px'}}>
            <div className='col-5'>
                <Select
                    options={properties}
                    style={{width: 200}}
                    value={[{label: filter.name, value: filter.value}]}
                    placeholder="Property key"
                    onChange={(item) => onSet('name', item.value)}
                    />
            </div>
            {filter.name && <div className='col-5'>
                <AsyncCreatableSelect
                    loadOptions={this.loadPropertyValues(filter.name)}
                    defaultOptions
                    formatCreateLabel={(inputValue) => inputValue}
                    key={filter.name} // forces a reload of the component when the property changes
                    placeholder="Property value"
                    style={{width: 200}}
                    value={{label: filter.value, value: filter.value}}
                    onChange={(item) => onSet('value', item.value)}
                    />
            </div>}
            <div className='col-1 cursor-pointer' onClick={() => onRemove(index)}>
                <CloseButton style={{fontSize: 37, lineHeight: '30px', color: 'hsl(0,0%,80%)'}} />
            </div>
        </div>
    }
}
PropertyFilter.propTypes = {
    properties: PropTypes.array.isRequired,
    filter: PropTypes.object.isRequired,
    onSet: PropTypes.func.isRequired
}
export default class PropertyFilters extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            filters: Object.keys(props.propertyFilters).map((key) => ({name: key, value: props.propertyFilters[key]}))
        }
        this.endpoint = !this.props.endpoint ? 'event' : this.props.endpoint;
        this.set = this.set.bind(this);
        this.update = this.update.bind(this);
        this.remove = this.remove.bind(this);
        if(!props.prefetchProperties) this.fetchProperties.call(this);
    }
    fetchProperties() {
        api.get('api/' + this.endpoint + '/properties').then((properties) =>
            this.setState({
                properties: properties.map((property) => (
                    {label: property.name, value: property.name}
                ))
            })
        )
    }
    componentDidUpdate(prevProps) {
        if(JSON.stringify(this.props.propertyFilters) != JSON.stringify(prevProps.propertyFilters)) {
            this.setState({filters: Object.keys(this.props.propertyFilters).map((key) => ({name: key, value: this.props.propertyFilters[key]}))});
        }
    }
    update(filters) {
        let dict = {};
        filters.map((item) => dict[item.name] = item.value)
        this.props.onChange(dict);
    }
    set(index, key, value) {
        let filters = [...this.state.filters];
        filters[index][key] = value;
        this.setState({filters})
        if(key == 'value') this.update(filters);
    }
    remove(index) {
        let filters = [...this.state.filters]
        filters.splice(index, 1)
        this.setState({filters});
        this.update(filters);
    }
    render() {
        let { filters } = this.state;
        let properties = this.state.properties ? this.state.properties : this.props.properties;
        return <div className={this.props.className || 'col-6'} style={{marginBottom: '2rem', padding: 0, ...this.props.style}}>
            {filters.map((filter, index) => <PropertyFilter
                properties={properties}
                key={index}
                onSet={(key, value) => this.set(index, key, value)}
                onRemove={() => this.remove(index)}
                endpoint={this.endpoint}
                filter={filter} />
            )}
            <button className='btn btn-sm btn-outline-success' onClick={() => this.setState({filters: [...filters, {}]})}>Add event property filter</button>
        </div>
    }
}

PropertyFilters.propTypes = {
    propertyFilters: PropTypes.objectOf(PropTypes.string).isRequired,
    onChange: PropTypes.func.isRequired,
    endpoint: PropTypes.string,
    properties: PropTypes.array
}