import React, { Component } from 'react'
import api from '../../api'
import AsyncCreatableSelect from 'react-select/async-creatable/dist/react-select.esm'
import { selectStyle } from '../../utils'
import PropTypes from 'prop-types'

export class PropertyValue extends Component {
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
