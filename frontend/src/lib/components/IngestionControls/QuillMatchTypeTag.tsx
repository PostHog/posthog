import { useValues } from 'kea'

import { Badge } from '@posthog/quill'

import { ingestionControlsLogic } from './ingestionControlsLogic'

export function QuillMatchTypeTag(): JSX.Element {
    const { matchType } = useValues(ingestionControlsLogic)

    return <Badge variant="destructive">{matchType === 'any' ? 'OR' : 'AND'}</Badge>
}
