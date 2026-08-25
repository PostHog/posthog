import { ReactNode } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { AlertState } from '~/queries/schema/schema-general'

import { AlertType } from '../types'

interface AlertDefinitionRowProps {
    label?: ReactNode
    children: ReactNode
    className?: string
}

export function AlertDefinitionRow({ label, children, className }: AlertDefinitionRowProps): JSX.Element {
    return (
        <div className={`flex flex-wrap gap-x-3 gap-y-2 items-center${className ? ` ${className}` : ''}`}>
            {label ? <div>{label}</div> : null}
            {children}
        </div>
    )
}

export function AlertStateIndicator({ alert }: { alert: AlertType }): JSX.Element {
    if (!alert.enabled) {
        return <LemonTag type="muted">Disabled</LemonTag>
    }

    switch (alert.state) {
        case AlertState.FIRING:
            return <LemonTag type="danger">Firing</LemonTag>
        case AlertState.ERRORED:
            return <LemonTag type="danger">Errored</LemonTag>
        case AlertState.SNOOZED:
            return <LemonTag type="completion">Snoozed</LemonTag>
        case AlertState.NOT_FIRING:
            return <LemonTag type="success">Not firing</LemonTag>
    }
}
