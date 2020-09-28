import React from 'react'
import { useValues } from 'kea'
import { Elements } from '~/toolbar/elements/Elements'
import { DraggableButton } from '~/toolbar/button/DraggableButton'
import { hot } from 'react-hot-loader/root'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { Fade } from 'lib/components/Fade/Fade'

export const ToolbarContainer = hot(_ToolbarContainer)
function _ToolbarContainer(): JSX.Element {
    const { buttonVisible } = useValues(toolbarLogic)

    return (
        <Fade visible={buttonVisible} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
            <Elements />
            <DraggableButton />
        </Fade>
    )
}
