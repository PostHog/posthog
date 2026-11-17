import { Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

/** The placeholder a quill list table shows for a cell with no value. */
export function QuillEmptyCell(): JSX.Element {
    return (
        <Text size="xs" variant="muted">
            –
        </Text>
    )
}

/** A relative time in a quill list table, with the exact time on hover, or the empty placeholder. */
export function QuillTimeCell({ time }: { time: string | null | undefined }): JSX.Element {
    if (!time) {
        return <QuillEmptyCell />
    }
    return (
        <Text size="xs" variant="muted" render={<span />}>
            <TZLabel time={time} />
        </Text>
    )
}
