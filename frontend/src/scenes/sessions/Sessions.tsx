import React from 'react'
import { SessionsTable } from './SessionsTable'
import { hot } from 'react-hot-loader/root'

export const Sessions = hot(_Sessions)
function _Sessions(): JSX.Element {
    return <SessionsTable />
}
