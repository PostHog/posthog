import { IconCheckCircle } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { IconCancel, IconExclamation, IconRadioButtonUnchecked, IconSync } from 'lib/lemon-ui/icons'
import { StatusTagSetting } from 'scenes/data-warehouse/utils'

import { ExternalDataJobStatus } from '~/types'

export function StatusIcon({ status }: { status?: ExternalDataJobStatus }): JSX.Element {
    if (!status) {
        return <IconRadioButtonUnchecked className="text-muted-foreground" />
    }

    if (status === ExternalDataJobStatus.Failed) {
        return <IconCancel className="text-destructive-foreground" />
    }
    if (status === ExternalDataJobStatus.BillingLimits || status === ExternalDataJobStatus.BillingLimitTooLow) {
        return <IconExclamation className="text-warning-foreground" />
    }
    if (status === ExternalDataJobStatus.Running) {
        return <IconSync className="animate-spin" />
    }
    if (status === ExternalDataJobStatus.Completed) {
        return <IconCheckCircle className="text-success" />
    }
    return <IconRadioButtonUnchecked className="text-muted-foreground" />
}

export function StatusTag({ status }: { status?: ExternalDataJobStatus }): JSX.Element {
    if (!status) {
        return (
            <LemonTag size="small" type="muted" className="px-1 rounded-lg">
                —
            </LemonTag>
        )
    }

    const type = StatusTagSetting[status] || 'muted'

    return (
        <LemonTag size="medium" type={type} className="px-1 rounded-lg">
            {status}
        </LemonTag>
    )
}
