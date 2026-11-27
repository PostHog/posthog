import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu, type LemonMenuSection } from 'lib/lemon-ui/LemonMenu'

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
    /** Absent when traces alerts are off, which leaves only `leadingSections` in the menu. */
    onCreateAlert?: (form: TracesAlertFormType) => void
    /** Sections shown above the alert presets, so a row needs only one menu button. */
    leadingSections?: LemonMenuSection[]
}

export function AlertOnThisMenu({
    target,
    source,
    onCreateAlert,
    leadingSections = [],
}: AlertOnThisMenuProps): JSX.Element {
    const scopeLabel = target.label ?? target.operation ?? target.serviceName

    return (
        <LemonMenu
            placement="bottom-end"
            items={[
                ...leadingSections,
                !!onCreateAlert && {
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
