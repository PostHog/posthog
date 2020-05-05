import React, { Component } from 'react'

import { LiveActionsTable } from './LiveActionsTable'

export class LiveActions extends Component {
    render() {
        return <LiveActionsTable {...this.props} />
    }
}
