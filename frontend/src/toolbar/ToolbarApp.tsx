import { useValues } from 'kea'
import { useRef, useState } from 'react'
import root from 'react-shadow'
import { Slide, ToastContainer } from 'react-toastify'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useSecondRender } from 'lib/hooks/useSecondRender'

import { ToolbarContainer } from '~/toolbar/ToolbarContainer'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { ToolbarProps } from '~/types'

import { TOOLBAR_ID } from './utils'
import { webVitalsToolbarLogic } from './web-vitals/webVitalsToolbarLogic'

type HTMLElementWithShadowRoot = HTMLElement & { shadowRoot: ShadowRoot }

export function ToolbarApp(props: ToolbarProps = {}): JSX.Element {
    const { apiURL } = useValues(toolbarConfigLogic(props))

    const shadowRef = useRef<HTMLElementWithShadowRoot | null>(null)
    const [didLoadStyles, setDidLoadStyles] = useState(false)

    // Preemptively mount the web vitals toolbar logic on mount
    // so that we collect the web vitals metrics since the beginning
    // TODO: Should probably mount the event debugger logic here too
    useOnMountEffect(() => {
        webVitalsToolbarLogic.mount()
    })

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
                  styleLink.href = `${apiURL}/static/toolbar.css?t=${timestampToNearestFiveMinutes}`
                  styleLink.onload = () => setDidLoadStyles(true)
                  const shadowRoot =
                      shadowRef.current?.shadowRoot || window.document.getElementById(TOOLBAR_ID)?.shadowRoot
                  shadowRoot?.getElementById('posthog-toolbar-styles')?.appendChild(styleLink)
              }
    )

    // There's a small conflict between our toolbar and the Tanstack React Dev library
    // because Tanstack is polluting the global event listeners with a mouse down listener
    // which conflicts with our toolbar's internal mouse down listeners
    //
    // To workaround that we simply prevent the event from bubbling further than the toolbar
    // See https://github.com/PostHog/posthog-js/issues/1425
    const onMouseDown = ({ nativeEvent: event }: React.MouseEvent<HTMLDivElement>): void => {
        event.stopImmediatePropagation()
    }

    return (
        <>
            <root.div id={TOOLBAR_ID} className="ph-no-capture" ref={shadowRef} onMouseDown={onMouseDown}>
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
