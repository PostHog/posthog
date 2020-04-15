import React, { Component } from 'react'
import Select from 'react-select'
import { CloseButton, selectStyle } from '../../utils'
import { PropertyValue } from './PropertyValue'
import PropTypes from 'prop-types'

export class PropertyFilter extends Component {
    constructor(props) {
        super(props)

        this.state = {}
    }
    render() {
        let { properties, index, item, onSet, onRemove, endpoint } = this.props
        let key = Object.keys(item)[0] ? Object.keys(item)[0].split('__') : []
        let value = Object.values(item)[0]
        let operatorMap = {
            null: 'equals',
            is_not: "doesn't equal",
            icontains: 'contains',
            not_icontains: "doesn't contain",
            gt: 'greater than',
            lt: 'lower than',
        }
        return (
            <div className="row" style={{ margin: '0.5rem -15px' }}>
                <div className="col-3" style={{ paddingRight: 0 }}>
                    <Select
                        options={properties}
                        style={{ width: 200 }}
                        value={[{ label: key[0], value: key[0] }]}
                        isLoading={!properties}
                        placeholder="Property key"
                        onChange={item =>
                            onSet(item.value + (key[1] ? '__' + key[1] : ''), item.value != key[0] ? '' : value)
                        }
                        styles={selectStyle}
                        autoFocus={!key[0]}
                        openMenuOnFocus={true}
                        menuPortalTarget={document.body}
                    />
                </div>
                {key[0] && (
                    <div className="col-3">
                        <Select
                            options={Object.entries(operatorMap).map(([key, value]) => ({
                                label: value,
                                value: key,
                            }))}
                            style={{ width: 200 }}
                            value={[
                                {
                                    label: operatorMap[key[1]] || 'equals',
                                    value: key[1],
                                },
                            ]}
                            placeholder="Property key"
                            onChange={operator => onSet(key[0] + '__' + operator.value, value)}
                            styles={selectStyle}
                            menuPortalTarget={document.body}
                        />
                    </div>
                )}
                {key[0] && (
                    <div className="col-5" style={{ paddingLeft: 0 }}>
                        <PropertyValue
                            endpoint={endpoint}
                            propertyKey={Object.keys(item)[0]}
                            value={value}
                            onSet={onSet}
                        />
                        {(key[1] == 'gt' || key[1] == 'lt') && isNaN(value) && (
                            <p className="text-danger">
                                Value needs to be a number. Try "equals" or "contains" instead.
                            </p>
                        )}
                    </div>
                )}
                <div className="col-1 cursor-pointer" onClick={() => onRemove(index)}>
                    <CloseButton style={{ float: 'none' }} />
                </div>
            </div>
        )
    }
}
PropertyFilter.propTypes = {
    properties: PropTypes.array,
    item: PropTypes.object.isRequired,
    onSet: PropTypes.func.isRequired,
}
