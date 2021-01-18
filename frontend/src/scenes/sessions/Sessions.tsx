import React from 'react'
import { SessionsView } from './SessionsView'
import { hot } from 'react-hot-loader/root'

export const Sessions = hot(_Sessions)
function _Sessions(): JSX.Element {
    return <SessionsView />
}
