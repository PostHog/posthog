import { useValues } from 'kea'
import { useRef, useState } from 'react'
import root from 'react-shadow'
import { Slide, ToastContainer } from 'react-toastify'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useSecondRender } from 'lib/hooks/useSecondRender'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { ToolbarContainer } from '~/toolbar/ToolbarContainer'
import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import { TOOLBAR_ID, toolbarStylesUrl } from './utils'
import { webVitalsToolbarLogic } from './web-vitals/webVitalsToolbarLogic'

type HTMLElementWithShadowRoot = HTMLElement & { shadowRoot: ShadowRoot }

export function ToolbarApp(props: ToolbarProps = {}): JSX.Element {
    const { apiHost } = useValues(toolbarConfigLogic(props))

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

                  // toolbar.css is loaded from the same place toolbar.js came
                  // from (a baked-in CDN path, else the bundle's own <script>
                  // src) so it tracks reverse-proxy prefixes, falling back to
                  // apiHost only when neither is available. See toolbarStylesUrl.
                  styleLink.href = toolbarStylesUrl(
                      __POSTHOG_TOOLBAR_PUBLIC_PATH__,
                      (window as any).__posthog_toolbar_script_src ?? null,
                      apiHost,
                      Date.now()
                  )

                  styleLink.onload = () => setDidLoadStyles(true)
                  // Without onerror the toolbar silently stays invisible when the
                  // CSS 404s (didLoadStyles never flips to true). That masks
                  // misconfigured apiHost / rejected URLs. Surface the failure
                  // via logger + telemetry and render the toolbar anyway —
                  // missing styles is a worse UX than nothing.
                  styleLink.onerror = () => {
                      toolbarLogger.error('config', 'Failed to load toolbar.css', { href: styleLink.href })
                      captureToolbarException(
                          new Error(`Failed to load toolbar.css from ${styleLink.href}`),
                          'toolbar_css_load'
                      )
                      toolbarPosthogJS.capture('toolbar css load failed', { href: styleLink.href })
                      setDidLoadStyles(true)
                  }
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
                <ToastContainer autoClose={60000} transition={Slide} position="bottom-center" />
            </root.div>
        </>
    )
}
