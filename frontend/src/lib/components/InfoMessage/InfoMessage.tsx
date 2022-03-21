import React from 'react'
import { AlertMessage, AlertMessageInterface } from './AlertMessage'

/** DEPRECATED: Use `AlertMessage` instead with type = 'info' */
export function InfoMessage(props: AlertMessageInterface): JSX.Element {
    return <AlertMessage {...props} />
}
