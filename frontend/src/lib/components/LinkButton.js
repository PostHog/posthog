import React from 'react'
import { router } from 'kea-router'
import { Button } from 'antd'

export function LinkButton({ to, ...props }) {
    return (
        <Button
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
