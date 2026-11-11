import { Tooltip } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'

// A trends row carries whole series (`data`, `days`, `filter`), so long values collapse to keep each row one line.
const INLINE_VALUE_MAX_LENGTH = 60

export function ResultCell({ value }: { value: unknown }): JSX.Element | null {
    if (value == null) {
        return null
    }
    const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
    if (text.length <= INLINE_VALUE_MAX_LENGTH) {
        return <>{text}</>
    }
    if (typeof value === 'object') {
        return (
            <div className="w-max max-w-120 overflow-x-auto">
                <JSONViewer src={value} collapsed displayObjectSize />
            </div>
        )
    }
    return (
        <Tooltip title={text}>
            <span className="block max-w-80 truncate">{text}</span>
        </Tooltip>
    )
}
