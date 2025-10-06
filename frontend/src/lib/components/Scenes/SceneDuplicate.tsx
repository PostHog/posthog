import { IconCopy } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

interface SceneDuplicateProps extends SceneDataAttrKeyProps {
    onClick: () => void
}

export function SceneDuplicate({ dataAttrKey, onClick }: SceneDuplicateProps): JSX.Element {
    return (
        <ButtonPrimitive
            menuItem
            onClick={onClick}
            data-attr={`${dataAttrKey}-duplicate-button`}
            tooltip="Duplicate resource"
        >
            <IconCopy />
            Duplicate
        </ButtonPrimitive>
    )
}
