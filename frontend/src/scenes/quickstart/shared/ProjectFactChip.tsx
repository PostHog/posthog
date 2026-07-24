import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { captureQuickstartAction } from './captureQuickstartAction'

// The facts every setup flow asks for, as three identically built chips: label | value | copy
export function ProjectFactChip({
    label,
    value,
    display,
    mono = true,
    copyTooltip,
    copyThing,
    action,
}: {
    label: string
    value: string
    /** Shown in the chip when it should differ from the copied value (e.g. region vs API host) */
    display?: string
    mono?: boolean
    copyTooltip: string
    copyThing: string
    action: string
}): JSX.Element {
    return (
        <div className="inline-flex items-stretch rounded border bg-bg-light overflow-hidden max-w-full min-w-0">
            <span className="flex items-center px-3 border-r bg-fill-tertiary text-xs font-medium text-secondary whitespace-nowrap">
                {label}
            </span>
            <span className={`${mono ? 'font-mono ' : ''}text-xs min-w-0 max-w-80 px-3 py-2 truncate`}>
                {display ?? value}
            </span>
            <div className="flex items-center px-2 border-l">
                <LemonButton
                    noPadding
                    icon={<IconCopy />}
                    tooltip={copyTooltip}
                    onClick={() => {
                        captureQuickstartAction(action)
                        void copyToClipboard(value, copyThing)
                    }}
                    data-attr={`quickstart-${action.replace(/_/g, '-')}`}
                />
            </div>
        </div>
    )
}
