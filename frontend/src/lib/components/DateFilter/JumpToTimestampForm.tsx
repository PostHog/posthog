import { ReactNode, useState } from 'react'

import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { WindowDirection, WindowSize, computeDateRange, parseTimestampInput } from './jumpToTimestampUtils'

const PLACEHOLDER_ISO = dayjs().format('YYYY-MM-DDTHH:mm:ss[Z]')
const PLACEHOLDER_UNIX = Math.floor(Date.now() / 1000).toString()

export interface JumpToTimestampFormProps {
    onSubmit: (dateFrom: string, dateTo: string) => void
    children: (props: { dateRange: { date_from: string; date_to: string } | null; submit: () => void }) => ReactNode
}

export function JumpToTimestampForm({ onSubmit, children }: JumpToTimestampFormProps): JSX.Element {
    const [timestampInput, setTimestampInput] = useState('')
    const [windowSize, setWindowSize] = useState<WindowSize>('5m')
    const [windowDirection, setWindowDirection] = useState<WindowDirection>('around')

    const hasInput = timestampInput.trim().length > 0
    const parsed = hasInput ? parseTimestampInput(timestampInput) : null
    const isInvalid = hasInput && !parsed

    const dateRange = parsed ? computeDateRange(parsed, windowSize, windowDirection) : null

    const handleSubmit = (): void => {
        if (dateRange) {
            onSubmit(dateRange.date_from, dateRange.date_to)
        }
    }

    const statusSuffix = parsed ? (
        <Tooltip title={`Parsed as: ${parsed.format('MMM D, YYYY HH:mm:ss')}`}>
            <IconCheck className="text-success text-base" />
        </Tooltip>
    ) : isInvalid ? (
        <Tooltip title="Could not parse timestamp. Try ISO 8601, unix seconds, or MM/DD/YYYY.">
            <IconWarning className="text-danger text-base" />
        </Tooltip>
    ) : null

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div
            onKeyDown={(e) => {
                if (e.key === 'Enter' && dateRange) {
                    e.preventDefault()
                    handleSubmit()
                }
            }}
        >
            <div className="space-y-2">
                <LemonInput
                    className="[&_input]:[color:var(--text-3000)]"
                    value={timestampInput}
                    onChange={setTimestampInput}
                    placeholder={`e.g. ${PLACEHOLDER_ISO}, ${PLACEHOLDER_UNIX}`}
                    fullWidth
                    autoFocus
                    size="small"
                    suffix={statusSuffix}
                    data-attr="jump-to-timestamp-input"
                />
                <div className="flex items-center gap-2">
                    <span className="text-xs font-medium whitespace-nowrap">Window:</span>
                    <LemonSelect
                        size="xsmall"
                        value={windowSize}
                        onChange={setWindowSize}
                        options={[
                            { value: '5m', label: '5 min' },
                            { value: '10m', label: '10 min' },
                            { value: '1h', label: '1 hour' },
                        ]}
                    />
                    <LemonSelect
                        size="xsmall"
                        value={windowDirection}
                        onChange={setWindowDirection}
                        options={[
                            { value: 'before', label: 'before' },
                            { value: 'around', label: 'around' },
                            { value: 'after', label: 'after' },
                        ]}
                    />
                </div>
            </div>
            {dateRange && (
                <div className="text-xs text-secondary mt-3">
                    Will show events from{' '}
                    <span className="whitespace-nowrap font-medium text-primary bg-fill-highlight-100 rounded px-0.5">
                        {dayjs(dateRange.date_from).format('MMM D, YYYY HH:mm')}
                    </span>{' '}
                    to{' '}
                    <span className="whitespace-nowrap font-medium text-primary bg-fill-highlight-100 rounded px-0.5">
                        {dayjs(dateRange.date_to).format('MMM D, YYYY HH:mm')}
                    </span>
                </div>
            )}
            {children({ dateRange, submit: handleSubmit })}
        </div>
    )
}
