import React, { Component } from 'react'

import { ActionEventsTable } from './ActionEventsTable'

export class ActionEvents extends Component {
    render() {
        return <ActionEventsTable {...this.props} />
    }
}
