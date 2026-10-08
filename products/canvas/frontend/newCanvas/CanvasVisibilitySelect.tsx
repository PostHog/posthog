import { useActions, useValues } from 'kea'

import { IconGlobe, IconLock } from '@posthog/icons'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Skeleton, Text } from '@posthog/quill'

import { visibilitySpace } from '../canvasVisibility'
import { canvasNewLogic } from './canvasNewLogic'

/** Who can see the new canvas, shown in the composer's footer. Private files it in the personal space, public in the team's. */
export function CanvasVisibilitySelect(): JSX.Element {
    const { spaces, spacesLoading, spacesUnavailable, selectedSpaceId, sending } = useValues(canvasNewLogic)
    const { setSelectedSpaceId, loadSpaces } = useActions(canvasNewLogic)

    if (spacesUnavailable) {
        return (
            <div className="flex flex-wrap items-center gap-2" role="alert">
                <Text size="xs" variant="destructive">
                    Couldn’t load who can see the canvas.
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
        return <Skeleton className="h-6 w-24" aria-label="Loading who can see the canvas" />
    }
    const privateSpace = visibilitySpace(spaces, 'private')
    const publicSpace = visibilitySpace(spaces, 'public')
    const options = [
        { space: privateSpace, label: 'Private', icon: <IconLock /> },
        { space: publicSpace, label: 'Public', icon: <IconGlobe /> },
    ]
    return (
        <Select
            value={selectedSpaceId ?? ''}
            disabled={sending || !privateSpace || !publicSpace}
            onValueChange={(value) => value && setSelectedSpaceId(String(value))}
        >
            {/* pinned: data-attr, renaming it breaks autocapture dashboards */}
            <SelectTrigger size="sm" aria-label="Who can see this canvas" data-attr="canvas-new-space">
                <SelectValue>
                    {(value: string) => {
                        const option = options.find((entry) => entry.space?.id === value) ?? options[0]
                        return (
                            <>
                                {option.icon}
                                {option.label}
                            </>
                        )
                    }}
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {options.map(
                    ({ space, label, icon }) =>
                        space && (
                            <SelectItem key={space.id} value={space.id}>
                                {icon}
                                {label}
                            </SelectItem>
                        )
                )}
            </SelectContent>
        </Select>
    )
}
