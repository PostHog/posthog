import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { AlertState } from '~/queries/schema/schema-general'

import { AlertType } from '../types'

export function AlertStateIndicator({ alert }: { alert: AlertType }): JSX.Element {
    switch (alert.state) {
        case AlertState.FIRING:
            return <LemonTag type="danger">FIRING</LemonTag>
        case AlertState.ERRORED:
            return <LemonTag type="danger">ERRORED</LemonTag>
        case AlertState.SNOOZED:
            return <LemonTag type="muted">SNOOZED</LemonTag>
        case AlertState.NOT_FIRING:
            return <LemonTag type="success">NOT FIRING</LemonTag>
    }
}
