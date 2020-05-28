import React, { Component } from 'react'
import { ActionsTable } from './ActionsTable'
import { hot } from 'react-hot-loader/root'

export const Actions = hot(_Actions)
class _Actions extends Component {
    constructor(props) {
        super(props)
    }
    render() {
        return <ActionsTable {...this.props} />
    }
}
