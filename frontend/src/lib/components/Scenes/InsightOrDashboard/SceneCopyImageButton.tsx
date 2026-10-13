import { useActions, useValues } from 'kea'

import { IconImage } from '@posthog/icons'

import { ButtonPrimitive, DisabledReasonsObject } from 'lib/ui/Button/ButtonPrimitives'

import { CaptureImageTarget, captureImageLogic } from './captureImageLogic'

interface SceneCopyImageButtonProps {
    target: CaptureImageTarget
    dataAttrKey: string
    disabledReasons?: DisabledReasonsObject
}

export function SceneCopyImageButton({ target, dataAttrKey, disabledReasons }: SceneCopyImageButtonProps): JSX.Element {
    const { copyImage } = useActions(captureImageLogic)
    const { isCapturing } = useValues(captureImageLogic)

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => copyImage(target)}
            data-attr={`${dataAttrKey}-copy-image`}
            tooltip="Copy the chart to your clipboard as a PNG"
            disabledReasons={{ ...disabledReasons, 'Copying…': isCapturing }}
        >
            <IconImage />
            Copy as PNG
        </ButtonPrimitive>
    )
}
