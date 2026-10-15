import clsx from 'clsx'

import { IconInfo, IconWarning } from '@posthog/icons'
import { LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import type { ScopeAccessLevel, ScopePickerRow } from 'lib/scopes'

interface ScopeAccessRowProps {
    row: ScopePickerRow
    /** Called with the row's scope object and the level the user picks. */
    onChange: (scopeObject: string, level: ScopeAccessLevel) => void
}

/** One scope object in a picker: its label and a No access / Read / Write control. */
export function ScopeAccessRow({ row, onChange }: ScopeAccessRowProps): JSX.Element {
    const { key, label, info, value, muted, warning, disabledReasons } = row
    return (
        <>
            <div className="flex items-center justify-between gap-2 min-h-8 group">
                <div className={clsx('flex items-center gap-1', muted && 'text-muted')}>
                    <b>{label}</b>
                    {info ? (
                        <Tooltip title={info}>
                            <IconInfo className="text-secondary text-base" />
                        </Tooltip>
                    ) : null}
                </div>
                <LemonSegmentedButton
                    onChange={(level) => onChange(key, level as ScopeAccessLevel)}
                    value={value}
                    options={[
                        { label: 'No access', value: 'none', disabledReason: disabledReasons.none },
                        { label: 'Read', value: 'read', disabledReason: disabledReasons.read },
                        { label: 'Write', value: 'write', disabledReason: disabledReasons.write },
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
