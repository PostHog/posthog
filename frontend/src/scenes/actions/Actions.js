import React, { Component } from 'react'
import { ActionsTable } from './ActionsTable'

export class Actions extends Component {
    constructor(props) {
        super(props)
    }
    render() {
        return <ActionsTable {...this.props} />
    }
}
