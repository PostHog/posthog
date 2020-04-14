import React, { Component } from 'react'
import PropTypes from 'prop-types'
import api from '../../api'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'

export class PropertyFilters extends Component {
    constructor(props) {
        super(props)

        this.state = {
            filters: Object.entries(props.propertyFilters).map(([key, value]) => {
                let dict = {}
                dict[key] = value
                return dict
            }),
        }
        this.endpoint = !this.props.endpoint ? 'event' : this.props.endpoint
        this.set = this.set.bind(this)
        this.update = this.update.bind(this)
        this.remove = this.remove.bind(this)
        if (props.properties === undefined) this.fetchProperties.call(this)
    }
    fetchProperties() {
        api.get('api/' + this.endpoint + '/properties').then(properties =>
            this.setState({
                properties: properties.map(property => ({
                    label: property.name,
                    value: property.name,
                })),
            })
        )
    }
    componentDidUpdate(prevProps) {
        if (JSON.stringify(this.props.propertyFilters) != JSON.stringify(prevProps.propertyFilters)) {
            this.setState({
                filters: Object.entries(this.props.propertyFilters).map(([key, value]) => {
                    let dict = {}
                    dict[key] = value
                    return dict
                }),
            })
        }
    }
    update(filters) {
        let dict = {}
        filters.map(item => (dict = { ...dict, ...item }))
        this.props.onChange(dict)
    }
    set(index, key, value) {
        let filters = [...this.state.filters]
        filters[index] = {}
        filters[index][key] = value
        console.log('setting', filters)
        this.setState({ filters })
        if (value) this.update(filters)
    }
    remove(index) {
        let filters = [...this.state.filters]
        filters.splice(index, 1)
        this.setState({ filters })
        this.update(filters)
    }
    render() {
        let { filters } = this.state
        let properties = this.state.properties ? this.state.properties : this.props.properties
        return (
            <div
                className={this.props.className || 'col-8'}
                style={{
                    marginBottom: '2rem',
                    padding: 0,
                    ...this.props.style,
                }}
            >
                {filters.map((item, index) => (
                    <span>
                        <PropertyFilter
                            properties={properties}
                            key={index}
                            onSet={(key, value) => this.set(index, key, value)}
                            onRemove={() => this.remove(index)}
                            endpoint={this.endpoint}
                            item={item}
                        />
                        {index != filters.length - 1 && (
                            <div className="row">
                                <div className="secondary offset-4 col-2" style={{ textAlign: 'center' }}>
                                    AND
                                </div>
                            </div>
                        )}
                    </span>
                ))}
                <Button
                    type="primary"
                    onClick={() => this.setState({ filters: [...filters, {}] })}
                    style={{ marginTop: '0.5rem' }}
                >
                    {filters.length == 0 ? 'Filter by property' : 'Add another filter'}
                </Button>
            </div>
        )
    }
}

PropertyFilters.propTypes = {
    propertyFilters: PropTypes.object.isRequired,
    onChange: PropTypes.func.isRequired,
    endpoint: PropTypes.string,
    properties: PropTypes.array,
}
