import { useActions, useValues } from 'kea'

import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Skeleton, Text } from '@posthog/quill'

import { canvasSpaceLabel } from '../canvasTasksApi'
import { canvasNewLogic } from './canvasNewLogic'

/** The space a new canvas goes in, shown in the composer's footer. */
export function CanvasSpaceSelect(): JSX.Element {
    const { spaces, spacesLoading, spacesUnavailable, selectedSpaceId, sending } = useValues(canvasNewLogic)
    const { setSelectedSpaceId, loadSpaces } = useActions(canvasNewLogic)

    if (spacesUnavailable) {
        return (
            <div className="flex flex-wrap items-center gap-2" role="alert">
                <Text size="xs" variant="destructive">
                    Your spaces didn’t load.
                </Text>
                <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    loading={spacesLoading}
                    onClick={() => loadSpaces()}
                    data-attr="canvas-new-spaces-retry"
                >
                    Try again
                </Button>
            </div>
        )
    }
    if (spaces === null) {
        return <Skeleton className="h-6 w-24" aria-label="Loading your spaces" />
    }
    return (
        <Select
            value={selectedSpaceId ?? ''}
            disabled={sending || !spaces.length}
            onValueChange={(value) => value && setSelectedSpaceId(String(value))}
        >
            <SelectTrigger size="sm" aria-label="Space" data-attr="canvas-new-space">
                <SelectValue>
                    {(value: string) => {
                        const space = spaces.find((entry) => entry.id === value)
                        return space ? `#${canvasSpaceLabel(space)}` : 'Pick a space'
                    }}
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {spaces.map((space) => (
                    <SelectItem key={space.id} value={space.id}>
                        {`#${canvasSpaceLabel(space)}`}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
