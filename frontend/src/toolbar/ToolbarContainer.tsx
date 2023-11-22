import { useValues } from 'kea'
import { Fade } from 'lib/components/Fade/Fade'

import { DraggableButton } from '~/toolbar/button/DraggableButton'
import { Elements } from '~/toolbar/elements/Elements'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export function ToolbarContainer(): JSX.Element {
    const { buttonVisible } = useValues(toolbarLogic)

    return (
        <Fade visible={buttonVisible} className="toolbar-global-fade-container ph-no-capture">
            <Elements />
            <DraggableButton />
        </Fade>
    )
}
