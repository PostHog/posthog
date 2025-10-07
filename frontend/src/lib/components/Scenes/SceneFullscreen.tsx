import { IconExpand45 } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

interface SceneFullscreenProps extends SceneDataAttrKeyProps {
    onClick: () => void
    isFullscreen: boolean
}

export function SceneFullscreen({ dataAttrKey, onClick, isFullscreen }: SceneFullscreenProps): JSX.Element {
    return (
        <ButtonPrimitive
            menuItem
            onClick={onClick}
            data-attr={`${dataAttrKey}-fullscreen-button`}
            tooltip={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            active={isFullscreen}
        >
            {isFullscreen ? <IconExpand45 className="text-warning" /> : <IconExpand45 />}
            Fullscreen
        </ButtonPrimitive>
    )
}
