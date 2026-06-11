import { IconCopy } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

interface SceneDuplicateProps extends SceneDataAttrKeyProps {
    onClick: () => void
    label?: string
    icon?: JSX.Element
    tooltip?: string
}

export function SceneDuplicate({
    dataAttrKey,
    onClick,
    label = 'Duplicate',
    icon = <IconCopy />,
    tooltip = 'Duplicate resource',
}: SceneDuplicateProps): JSX.Element {
    return (
        <ButtonPrimitive menuItem onClick={onClick} data-attr={`${dataAttrKey}-duplicate-button`} tooltip={tooltip}>
            {icon}
            {label}
        </ButtonPrimitive>
    )
}
