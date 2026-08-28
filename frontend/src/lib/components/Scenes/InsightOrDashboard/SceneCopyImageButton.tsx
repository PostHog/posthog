import { useActions, useValues } from 'kea'

import { IconImage } from '@posthog/icons'

import { ButtonPrimitive, DisabledReasonsObject } from 'lib/ui/Button/ButtonPrimitives'

import { copyImageLogic } from './copyImageLogic'

interface SceneCopyImageButtonProps {
    /** CSS selector for the element to capture. */
    selector: string
    dataAttrKey: string
    disabledReasons?: DisabledReasonsObject
}

export function SceneCopyImageButton({
    selector,
    dataAttrKey,
    disabledReasons,
}: SceneCopyImageButtonProps): JSX.Element {
    const { copyImage } = useActions(copyImageLogic)
    const { isCopying } = useValues(copyImageLogic)

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => copyImage(selector)}
            data-attr={`${dataAttrKey}-copy-image`}
            tooltip="Copy the chart to your clipboard as a PNG"
            disabledReasons={{ ...disabledReasons, 'Copying…': isCopying }}
        >
            <IconImage />
            Copy as PNG
        </ButtonPrimitive>
    )
}
