import { IconBox } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

export function FilteredStackTrace({
    framesCount,
    onShowAllFrames,
}: {
    framesCount: number
    exceptionCount: number
    onShowAllFrames: () => void
}): JSX.Element {
    return (
        <div className="border-1 flex items-center justify-between rounded border-border p-1 text-muted-foreground">
            <p className="my-0 pl-1 text-xs font-medium text-muted-foreground">{framesCount} vendor frames</p>
            <ButtonPrimitive onClick={onShowAllFrames} size="xs" className="text-muted-foreground">
                <IconBox />
                Show all frames
            </ButtonPrimitive>
        </div>
    )
}
