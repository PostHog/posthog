import React, { Component } from 'react'
import PropTypes from 'prop-types'
import Select from 'react-select'
import AsyncCreatableSelect from 'react-select/async-creatable'
import api from './Api';
import { selectStyle, CloseButton } from './utils';


class PropertyValue extends Component {
    constructor(props) {
        super(props)
        this.state = {input: props.value};
        this.loadPropertyValues = this.loadPropertyValues.bind(this);
        this.ref = React.createRef();
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
        let { propertyKey, onSet, value } = this.props;
        let { isEditing, input } = this.state;
        return <span ref={this.ref} className='property-value'>
            <AsyncCreatableSelect
            loadOptions={this.loadPropertyValues(propertyKey.split('__')[0])}
            defaultOptions={true}
            cacheOptions
            formatCreateLabel={(inputValue) => "Specify: " + inputValue}
            allowCreateWhileLoading={true}
            createOptionPosition="first"
            key={propertyKey} // forces a reload of the component when the property changes
            placeholder="Property value"
            style={{width: 200}}
            value={{label: value, value: value}}
            // Make it look like normal input
            components={{DropdownIndicator: null, IndicatorSeparator: null}}
            onChange={(out) => {
                onSet(propertyKey, out.value)
                this.setState({input: out.value})
                this.select.blur();
            }}
            autoFocus={!value}
            styles={selectStyle}
            ref={ref => {
                this.select = ref;
            }}
            // This is a series of hacks to make the text editable
            inputValue={isEditing ? this.state.input : null}
            onFocus={() => this.setState({isEditing: true})}
            onInputChange={(input, actionMeta) => {
                if (actionMeta.action == "input-change") {
                    this.setState({ input });
                    return input;
                }
                return this.state.input;
            }}
            />
        </span>
    }
}
PropertyValue.propTypes = {
    propertyKey: PropTypes.string.isRequired,
    value: PropTypes.any.isRequired,
    onSet: PropTypes.func.isRequired
}

export class PropertyFilter extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
    }   
    render() {
        let { properties, index, item, onSet, onRemove, endpoint } = this.props;
        let key = Object.keys(item)[0] ? Object.keys(item)[0].split('__') : [];
        let value = Object.values(item)[0];
        let operatorMap = {
            null: 'equals',
            'icontains': 'contains',
            'gt': 'greater than',
            'lt': 'lower than'
        }
        return <div className='row' style={{margin: '0.5rem -15px'}}>
            <div className='col-4' style={{paddingRight: 0}}>
                <Select
                    options={properties}
                    style={{width: 200}}
                    value={[{label: key[0], value: key[0]}]}
                    placeholder="Property key"
                    onChange={(item) => onSet(item.value + (key[1] ? '__' + key[1] : ''), (item.value != key[0] ? '' : value))}
                    styles={selectStyle}
                    autoFocus={!key[0]}
                    openMenuOnFocus={true}
                    />
            </div>
            {key[0] && <div className='col-2'>
                <Select
                    options={Object.entries(operatorMap).map(([key, value]) => ({label: value, value: key}))}
                    style={{width: 200}}
                    value={[{label: operatorMap[key[1]] || 'equals', value: key[1]}]}
                    placeholder="Property key"
                    onChange={(operator) => onSet(key[0] + '__' + operator.value, value)}
                    styles={selectStyle}
                    styles={selectStyle}
                    />
            </div>}
            {key[0] && <div className='col-5' style={{paddingLeft: 0}}>
                <PropertyValue endpoint={endpoint} propertyKey={Object.keys(item)[0]} value={value} onSet={onSet} />
                {(key[1] == 'gt' || key[1] == 'lt') && isNaN(value) && <p className='text-danger'>Value needs to be a number. Try "equals" or "contains" instead.</p>}
            </div>}
            <div className='col-1 cursor-pointer' onClick={() => onRemove(index)}>
                <CloseButton style={{float: 'none'}} />
            </div>
        </div>
    }
}
PropertyFilter.propTypes = {
    properties: PropTypes.array.isRequired,
    item: PropTypes.object.isRequired,
    onSet: PropTypes.func.isRequired
}
export default class PropertyFilters extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            filters: Object.entries(props.propertyFilters).map(([key, value]) => {
                let dict = {};
                dict[key] = value;
                return dict;
            })
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
            this.setState({filters: Object.entries(this.props.propertyFilters).map(([key, value]) => {
                let dict = {};
                dict[key] = value;
                return dict;
            })})
        }
    }
    update(filters) {
        let dict = {};
        filters.map((item) => dict = {...dict, ...item})
        this.props.onChange(dict);
    }
    set(index, key, value) {
        let filters = [...this.state.filters];
        filters[index] = {};
        filters[index][key] = value;
        console.log('setting', filters)
        this.setState({filters})
        if(value) this.update(filters);
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
        return <div className={this.props.className || 'col-8'} style={{marginBottom: '2rem', padding: 0, ...this.props.style}}>
            {filters.map((item, index) => <span>
                <PropertyFilter
                    properties={properties}
                    key={index}
                    onSet={(key, value) => this.set(index, key, value)}
                    onRemove={() => this.remove(index)}
                    endpoint={this.endpoint}
                    item={item} />
                {index != filters.length -1 && <div className='row'><div className='secondary offset-4 col-2' style={{textAlign: 'center'}}>AND</div></div>}
            </span>)}
            <button className='btn btn-sm btn-outline-success' onClick={() => this.setState({filters: [...filters, {}]})} style={{marginTop: '0.5rem'}}>
                Add event property filter
            </button>
        </div>
    }
}

PropertyFilters.propTypes = {
    propertyFilters: PropTypes.objectOf(PropTypes.string, PropTypes.number).isRequired,
    onChange: PropTypes.func.isRequired,
    endpoint: PropTypes.string,
    properties: PropTypes.array
}
