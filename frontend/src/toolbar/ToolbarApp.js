import React, { useRef, useEffect } from 'react'
import { dockLogic } from '~/toolbar/dockLogic'
import { useSecondRender } from 'lib/hooks/useSecondRender'
import root from 'react-shadow'
import { ToolbarContainer } from '~/toolbar/ToolbarContainer'
import { useMountedLogic } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { posthog } from '~/toolbar/posthog'

export function ToolbarApp(props) {
    useMountedLogic(toolbarLogic(props))

    const shadowRef = useRef(null)
    useMountedLogic(dockLogic({ shadowRef }))

    useEffect(() => {
        if (props.instrument) {
            posthog.identify(null, { email: props.userEmail })
            posthog.optIn()
        }
    }, [])

    // this runs after the shadow root has been added to the dom
    const didRender = useSecondRender(() => {
        function addStyleElementToShadowRoot(element) {
            const { shadowRoot } = shadowRef.current || window.document.getElementById('__POSTHOG_TOOLBAR__')
            shadowRoot.getElementById('posthog-toolbar-styles').appendChild(element)
        }

        if (window.__PHGTLB_STYLES__) {
            window.__PHGTLB_STYLES__.forEach((element) => addStyleElementToShadowRoot(element))
        }
        window.__PHGTLB_ADD_STYLES__ = (element) => addStyleElementToShadowRoot(element)
    })

    return (
        <>
            <root.div id="__POSTHOG_TOOLBAR__" ref={shadowRef}>
                <div id="posthog-toolbar-styles" />
                {didRender ? <ToolbarContainer {...props} shadowRef={shadowRef} /> : null}
            </root.div>
        </>
    )
}
