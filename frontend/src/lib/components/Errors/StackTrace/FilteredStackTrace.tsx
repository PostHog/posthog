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
        <div className="border-1 rounded flex justify-between items-center p-1 text-secondary">
            <p className="text-xs font-medium my-0 pl-1 text-secondary">{framesCount} vendor frames</p>
            <ButtonPrimitive onClick={onShowAllFrames} size="xs" className="text-secondary">
                <IconBox />
                Show all frames
            </ButtonPrimitive>
        </div>
    )
}
