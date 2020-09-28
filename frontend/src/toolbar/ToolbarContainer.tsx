import React from 'react'
import { useValues } from 'kea'
import { Elements } from '~/toolbar/elements/Elements'
import { DraggableButton } from '~/toolbar/button/DraggableButton'
import { hot } from 'react-hot-loader/root'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export const ToolbarContainer = hot(_ToolbarContainer)
function _ToolbarContainer(): JSX.Element {
    const { buttonVisible } = useValues(toolbarLogic)

    return buttonVisible ? (
        <>
            <Elements />
            <DraggableButton />
        </>
    ) : (
        <></>
    )
}
