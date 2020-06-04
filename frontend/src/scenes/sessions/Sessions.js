import React from 'react'
import { SessionsTable } from './SessionsTable'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { hot } from 'react-hot-loader/root'

export const logic = sessionsTableLogic

export const Sessions = hot(_Sessions)
function _Sessions(props) {
    return <SessionsTable {...props} logic={sessionsTableLogic} />
}
