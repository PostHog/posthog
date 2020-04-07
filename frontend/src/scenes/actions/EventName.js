import React, { Component } from 'react'
import api from '../../lib/api'
import Select from 'react-select'
import PropTypes from 'prop-types'

export class EventName extends Component {
    constructor(props) {
        super(props)

        this.state = {}
        this.fetchNames()
    }
    fetchNames = () => {
        api.get('api/event/names').then(names =>
            this.setState({
                names: names
                    .map(name => ({
                        value: name.name,
                        label: name.name + ' (' + name.count + ' events)',
                    }))
                    .filter(item => item.value != '$autocapture' && item.value != '$pageview'),
            })
        )
    }
    render() {
        let { names } = this.state
        return (
            <span>
                <Select
                    options={names}
                    isSearchable={true}
                    isClearable={true}
                    onChange={this.props.onChange}
                    isLoading={!names}
                    disabled={names && names.length == 0}
                    value={
                        this.props.value &&
                        this.state.names &&
                        this.state.names.filter(item => this.props.value == item.value)[0]
                    }
                />
                <br />
                {names && names.length === 0 && "You haven't sent any custom events."}{' '}
                <a href="https://github.com/PostHog/posthog/wiki/Integrations" target="_blank">
                    See documentation
                </a>{' '}
                on how to send custom events in lots of languages.
            </span>
        )
    }
}
EventName.propTypes = {
    onChange: PropTypes.func.isRequired,
    value: PropTypes.string.isRequired,
}
