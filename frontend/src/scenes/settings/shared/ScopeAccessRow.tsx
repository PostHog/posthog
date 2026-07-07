import clsx from 'clsx'

import { IconInfo, IconWarning } from '@posthog/icons'
import { LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

interface ScopeAccessRowProps {
    /** Display label for the scope (e.g. 'Feature flag', 'Endpoint'). */
    label: string
    /** Currently selected action: 'none' | 'read' | 'write'. */
    value: string
    /** Called with the new value when the user picks an option. */
    onChange: (value: string) => void
    /** Reason the No access option should be disabled. Set to a non-empty string to disable (e.g. a required scope). */
    noneDisabledReason?: string
    /** Reason the Read option should be disabled. Set to a non-empty string to disable. */
    readDisabledReason?: string
    /** Reason the Write option should be disabled. Set to a non-empty string to disable. */
    writeDisabledReason?: string
    /** Optional tooltip content shown next to the label via an info icon. */
    info?: string | JSX.Element
    /** When true, the label is dimmed (e.g. when the row is contextually disabled). */
    muted?: boolean
    /** Optional warning content rendered as a sub-row below the main row. */
    warning?: string | JSX.Element | null
}

export function ScopeAccessRow({
    label,
    value,
    onChange,
    noneDisabledReason,
    readDisabledReason,
    writeDisabledReason,
    info,
    muted = false,
    warning,
}: ScopeAccessRowProps): JSX.Element {
    return (
        <>
            <div className="flex items-center justify-between gap-2 min-h-8 group">
                <div className={clsx('flex items-center gap-1', muted && 'text-muted')}>
                    <b className="transition-colors group-hover:text-highlight">{label}</b>
                    {info ? (
                        <Tooltip title={info}>
                            <IconInfo className="text-secondary text-base" />
                        </Tooltip>
                    ) : null}
                </div>
                <LemonSegmentedButton
                    onChange={onChange}
                    value={value}
                    options={[
                        { label: 'No access', value: 'none', disabledReason: noneDisabledReason },
                        { label: 'Read', value: 'read', disabledReason: readDisabledReason },
                        { label: 'Write', value: 'write', disabledReason: writeDisabledReason },
                    ]}
                    size="xsmall"
                />
            </div>
            {warning ? (
                <div className="flex items-start gap-2 text-xs italic pb-2">
                    <IconWarning className="text-base text-secondary mt-0.5" />
                    <span>{warning}</span>
                </div>
            ) : null}
        </>
    )
}
