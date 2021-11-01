import React, { useRef, useState } from 'react'
import { useSecondRender } from 'lib/hooks/useSecondRender'
import root from 'react-shadow'
import { ToolbarContainer } from '~/toolbar/ToolbarContainer'
import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ToolbarProps } from '~/types'
import { Slide, ToastContainer } from 'react-toastify'

type HTMLElementWithShadowRoot = HTMLElement & { shadowRoot: ShadowRoot }

export function ToolbarApp(props: ToolbarProps = {}): JSX.Element {
    const { jsURL } = useValues(toolbarLogic(props))

    const shadowRef = useRef<HTMLElementWithShadowRoot | null>(null)
    const [didLoadStyles, setDidLoadStyles] = useState(false)

    // this runs after the shadow root has been added to the dom
    const didRender = useSecondRender(
        props.disableExternalStyles
            ? () => {}
            : () => {
                  const styleLink = document.createElement('link')
                  styleLink.rel = 'stylesheet'
                  styleLink.type = 'text/css'
                  styleLink.href = `${jsURL}/static/toolbar.css`
                  styleLink.onload = () => setDidLoadStyles(true)
                  const shadowRoot =
                      shadowRef.current?.shadowRoot || window.document.getElementById('__POSTHOG_TOOLBAR__')?.shadowRoot
                  shadowRoot?.getElementById('posthog-toolbar-styles')?.appendChild(styleLink)
              }
    )

    return (
        <>
            <root.div id="__POSTHOG_TOOLBAR__" className="ph-no-capture" ref={shadowRef}>
                <div id="posthog-toolbar-styles" />
                {didRender && (didLoadStyles || props.disableExternalStyles) ? <ToolbarContainer /> : null}
                <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
            </root.div>
        </>
    )
}
