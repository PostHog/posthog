import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import {
    TRACES_ALERT_PRESETS,
    TracesAlertPresetTarget,
    buildTargetPresetForm,
} from 'products/tracing/frontend/alerting/tracesAlertPresets'
import type { TracesAlertFormType } from 'products/tracing/frontend/alerting/tracesAlertUtils'

export interface AlertOnThisMenuProps {
    target: TracesAlertPresetTarget
    /** Which table the row is in, for the menu's `data-attr`s. */
    source: 'services' | 'endpoints'
    onCreateAlert: (form: TracesAlertFormType) => void
}

export function AlertOnThisMenu({ target, source, onCreateAlert }: AlertOnThisMenuProps): JSX.Element {
    const scopeLabel = target.label ?? target.operation ?? target.serviceName

    return (
        <LemonMenu
            placement="bottom-end"
            items={[
                {
                    title: 'Alert on this',
                    items: TRACES_ALERT_PRESETS.map(({ value, label }) => ({
                        label,
                        'data-attr': `apm-${source}-alert-${value}`,
                        onClick: () => onCreateAlert(buildTargetPresetForm(target, value)),
                    })),
                },
            ]}
        >
            <LemonButton
                size="xsmall"
                icon={<IconEllipsis />}
                aria-label={`More options for ${scopeLabel}`}
                data-attr={`apm-${source}-row-menu`}
            />
        </LemonMenu>
    )
}
