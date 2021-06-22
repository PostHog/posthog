import React from 'react'
// import {Link} from "./Link"
import { HighlightedItems } from 'scenes/persons/personsLogic'

export interface DeepLinkProps extends React.HTMLProps<HTMLAnchorElement> {
    context: HighlightedItems
    to: string
}

/*
 * This component is to be used for deep linking to specific sessions, events, and/or
 * recordings within a given page. This component simply hijacks the `to` prop
 * and injects deep link context as hash parameters
 */
// export function DeepLink({context, to, ...linkProps}: DeepLinkProps): JSX.Element {
//     const toWithContext = to
//     return <Link to={toWithContext} {...linkProps}/>
// }
