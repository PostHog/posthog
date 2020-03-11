import React, { Component } from 'react'
import api from '../../lib/api'
import Select from 'react-select'
import PropTypes from 'prop-types'

export class EventName extends Component {
    constructor(props) {
        super(props)

        this.state = {
        }
        this.fetchNames.call(this);
    }
    fetchNames() {
        api.get('api/event/names').then((names) => this.setState({
            names: names.map((name) => ({
                value: name.name,
                label: name.name + ' (' + name.count + ' events)'
            })).filter((item) => item.value != '$autocapture' && item.value != '$pageview')
        }))
    }
    render() {
        if(this.props.value == '$autocapture' || this.props.value == '$pageview') return <input type="text" disabled value={this.props.value} className='form-control' />;
        return this.state.names ? <Select
            options={this.state.names}
            isSearchable={true}
            isClearable={true}
            onChange={this.props.onChange}
            value={this.props.value && this.state.names.filter((item) => this.props.value == item.value)[0]}
        /> : null;
    }
}
EventName.propTypes = {
    onChange: PropTypes.func.isRequired,
    value: PropTypes.string.isRequired
}
