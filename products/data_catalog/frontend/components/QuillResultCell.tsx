import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { JSONViewer } from 'lib/components/JSONViewer'

import { INLINE_VALUE_MAX_LENGTH } from './ResultCell'

export function QuillResultCell({ value }: { value: unknown }): JSX.Element | null {
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
        <Tooltip>
            <TooltipTrigger render={<span className="block max-w-80 truncate" />}>{text}</TooltipTrigger>
            <TooltipContent>{text}</TooltipContent>
        </Tooltip>
    )
}
