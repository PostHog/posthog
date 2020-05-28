import React, { Component } from 'react'

import { LiveActionsTable } from './LiveActionsTable'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { connect } from 'kea'
import { hot } from 'react-hot-loader/root'

export const logic = connect(() => [
    eventsTableLogic({ fixedFilters: undefined, apiUrl: 'api/event/actions/', live: true }),
])

export const LiveActions = hot(_LiveActions)
class _LiveActions extends Component {
    render() {
        return <LiveActionsTable {...this.props} />
    }
}
