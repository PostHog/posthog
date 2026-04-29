import { IconCheckCircle } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { IconCancel, IconExclamation, IconRadioButtonUnchecked, IconSync } from 'lib/lemon-ui/icons'

import { ExternalDataJobStatus } from '~/types'

import { StatusTagSetting } from 'products/data_warehouse/frontend/utils'

export function StatusIcon({ status }: { status?: ExternalDataJobStatus }): JSX.Element {
    if (!status) {
        return <IconRadioButtonUnchecked className="text-muted" />
    }

    if (status === ExternalDataJobStatus.Failed) {
        return <IconCancel className="text-danger" />
    }
    if (status === ExternalDataJobStatus.BillingLimits || status === ExternalDataJobStatus.BillingLimitTooLow) {
        return <IconExclamation className="text-warning" />
    }
    if (status === ExternalDataJobStatus.Running) {
        return <IconSync className="animate-spin" />
    }
    if (status === ExternalDataJobStatus.Completed) {
        return <IconCheckCircle className="text-success" />
    }
    return <IconRadioButtonUnchecked className="text-muted" />
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
