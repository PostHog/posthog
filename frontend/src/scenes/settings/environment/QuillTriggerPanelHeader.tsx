import { Text } from '@posthog/quill'

import { QuillMatchTypeTag } from 'lib/components/IngestionControls/QuillMatchTypeTag'

export function QuillTriggerPanelHeader({
    title,
    status,
    showMatchTag = false,
}: {
    title: string
    status: string
    showMatchTag?: boolean
}): JSX.Element {
    return (
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="flex items-center gap-1 font-semibold">
                {showMatchTag && <QuillMatchTypeTag />}
                {title}
            </span>
            <Text size="xs" variant="muted" render={<span className="m-0 font-normal" />}>
                {status}
            </Text>
        </span>
    )
}
