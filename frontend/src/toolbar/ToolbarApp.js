import React, { useRef } from 'react'
import { dockLogic } from '~/toolbar/dockLogic'
import { useSecondRender } from 'lib/hooks/useSecondRender'
import root from 'react-shadow'
import { ToolbarContainer } from '~/toolbar/ToolbarContainer'

export function ToolbarApp(props) {
    const shadowRef = useRef(null)
    const logic = dockLogic({ shadowRef })

    // this runs after the shadow root has been added to the dom
    const didRender = useSecondRender(() => {
        function addStyleElementToShadowRoot(element) {
            const { shadowRoot } = shadowRef.current || window.document.getElementById('__POSTHOG_TOOLBAR__')
            shadowRoot.getElementById('posthog-toolbar-styles').appendChild(element)
        }

        if (window.__PHGTLB_STYLES__) {
            window.__PHGTLB_STYLES__.forEach(element => addStyleElementToShadowRoot(element))
        }
        window.__PHGTLB_ADD_STYLES__ = element => addStyleElementToShadowRoot(element)
    })

    return (
        <>
            <root.div id="__POSTHOG_TOOLBAR__" ref={shadowRef}>
                <div id="posthog-toolbar-styles" />
                {didRender ? <ToolbarContainer {...props} dockLogic={logic} shadowRef={shadowRef} /> : null}
            </root.div>
        </>
    )
}
