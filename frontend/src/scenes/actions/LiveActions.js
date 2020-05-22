import React, { Component } from 'react'

import { LiveActionsTable } from './LiveActionsTable'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { connect } from 'kea'

export const logic = connect(() => [
    eventsTableLogic({ fixedFilters: undefined, apiUrl: 'api/event/actions/', live: true }),
])

export class LiveActions extends Component {
    render() {
        return <LiveActionsTable {...this.props} />
    }
}
