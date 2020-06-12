import React from 'react'
import { ActionsTable } from './ActionsTable'
import { hot } from 'react-hot-loader/root'

function _Actions(props) {
    return <ActionsTable {...props} />
}
export const Actions = hot(_Actions)
