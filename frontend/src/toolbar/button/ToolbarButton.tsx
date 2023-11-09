import './ToolbarButton.scss'
import { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { getShadowRoot } from '~/toolbar/utils'
import { Toolbar3000 } from '../3000/Toolbar3000'

export const HELP_URL =
    'https://posthog.com/docs/user-guides/toolbar?utm_medium=in-product&utm_campaign=toolbar-help-button'

export function ToolbarButton(): JSX.Element {
    const { setBoundingRect } = useActions(toolbarButtonLogic)

    const { isAuthenticated } = useValues(toolbarLogic)

    const globalMouseMove = useRef((e: MouseEvent) => {
        e
    })

    useEffect(() => {
        globalMouseMove.current = function (): void {
            const buttonDiv = getShadowRoot()?.getElementById('button-toolbar')
            if (buttonDiv) {
                const rect = buttonDiv.getBoundingClientRect()

                // TODO this is already capturing x and y change
                // TODO and could replace react draggable
                setBoundingRect(rect)
            }
        }
        window.addEventListener('mousemove', globalMouseMove.current)
        return () => window.removeEventListener('mousemove', globalMouseMove.current)
    }, [isAuthenticated])

    return <Toolbar3000 />
}
