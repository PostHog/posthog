import React from 'react'
import { router } from 'kea-router'

// use <A href=''> instead of <a href=''> to open links via the router
export function Link({ to, ...props }) {
    return (
        <a
            href={to}
            {...props}
            onClick={event => {
                if (!props.target) {
                    event.preventDefault()
                    event.stopPropagation()
                    router.actions.push(to) // router is mounted automatically, so this is safe to call
                }
                props.onClick && props.onClick(event)
            }}
        />
    )
}
