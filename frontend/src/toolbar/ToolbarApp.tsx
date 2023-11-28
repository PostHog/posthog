import { useValues } from 'kea'
import { useSecondRender } from 'lib/hooks/useSecondRender'
import { useRef, useState } from 'react'
import root from 'react-shadow'
import { Slide, ToastContainer } from 'react-toastify'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { ToolbarContainer } from '~/toolbar/ToolbarContainer'
import { ToolbarProps } from '~/types'

type HTMLElementWithShadowRoot = HTMLElement & { shadowRoot: ShadowRoot }

export function ToolbarApp(props: ToolbarProps = {}): JSX.Element {
    const { jsURL } = useValues(toolbarConfigLogic(props))

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
                  // toolbar.js is served from the PostHog CDN, this has a TTL of 24 hours.
                  // the toolbar asset includes a rotating "token" that is valid for 5 minutes.
                  const fiveMinutesInMillis = 5 * 60 * 1000
                  // this ensures that we bust the cache periodically
                  const timestampToNearestFiveMinutes =
                      Math.floor(Date.now() / fiveMinutesInMillis) * fiveMinutesInMillis
                  styleLink.href = `${jsURL}/static/toolbar.css?t=${timestampToNearestFiveMinutes}`
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
                <ToastContainer
                    autoClose={60000}
                    transition={Slide}
                    closeOnClick={false}
                    draggable={false}
                    position="bottom-center"
                />
            </root.div>
        </>
    )
}
