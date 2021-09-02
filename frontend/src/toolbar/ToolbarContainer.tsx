import React from 'react'
import { useValues } from 'kea'
import { Elements } from '~/toolbar/elements/Elements'
import { DraggableButton } from '~/toolbar/button/DraggableButton'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { Fade } from 'lib/components/Fade/Fade'
import { ElementSelection } from '~/toolbar/tours/ElementSelection'
import { PreviewTour } from '~/toolbar/tours/PreviewTour'

export function ToolbarContainer(): JSX.Element {
    const { buttonVisible } = useValues(toolbarLogic)

    return (
        <Fade visible={buttonVisible} className="toolbar-global-fade-container ph-no-capture">
            <Elements />
            <DraggableButton />
            <ElementSelection />
            <PreviewTour />
        </Fade>
    )
}
