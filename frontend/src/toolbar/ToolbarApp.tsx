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

import { TOOLBAR_ID, toolbarAssetBaseUrl } from './utils'
import { webVitalsToolbarLogic } from './web-vitals/webVitalsToolbarLogic'

type HTMLElementWithShadowRoot = HTMLElement & { shadowRoot: ShadowRoot }

export function ToolbarApp(props: ToolbarProps = {}): JSX.Element {
    const { apiHost, apiHostResolution } = useValues(toolbarConfigLogic(props))

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

                  // When __POSTHOG_TOOLBAR_PUBLIC_PATH__ is baked in at build
                  // time (posthog-js versioned bundle), load the CSS from the
                  // same versioned URL as the JS bundle. The version is the
                  // cache key, so no cache-busting query param is needed.
                  //
                  // Otherwise (i.e. posthog/posthog's own deploys), fall back to
                  // serving toolbar.css from the API host alongside toolbar.js,
                  // with a 5-minute cache-buster on the unversioned URL.
                  if (__POSTHOG_TOOLBAR_PUBLIC_PATH__) {
                      styleLink.href = `${__POSTHOG_TOOLBAR_PUBLIC_PATH__}toolbar.css`
                  } else {
                      const fiveMinutesInMillis = 5 * 60 * 1000
                      const timestampToNearestFiveMinutes =
                          Math.floor(Date.now() / fiveMinutesInMillis) * fiveMinutesInMillis

                      // apiHost falls back to the page origin when api_host / apiURL
                      // are absent or rejected (see apiHostResolution). The customer's
                      // own origin doesn't serve /static/toolbar.css, so in that case
                      // load it from wherever toolbar.js itself was served — that host
                      // is known-good because the bundle running this code came from it.
                      const fallbackBase = apiHostResolution.source.startsWith('fallback_')
                          ? toolbarAssetBaseUrl((window as any).__posthog_toolbar_script_src)
                          : null
                      styleLink.href = fallbackBase
                          ? `${fallbackBase}toolbar.css?t=${timestampToNearestFiveMinutes}`
                          : `${apiHost}/static/toolbar.css?t=${timestampToNearestFiveMinutes}`
                  }

                  styleLink.onload = () => setDidLoadStyles(true)
                  // Without onerror the toolbar silently stays invisible when the
                  // CSS 404s (didLoadStyles never flips to true). That masks
                  // misconfigured apiHost / rejected URLs. Surface the failure
                  // via logger + telemetry and render the toolbar anyway —
                  // missing styles is a worse UX than nothing.
                  styleLink.onerror = () => {
                      const href = styleLink.href
                      // Drop the `?t=` cache-buster from the thrown message: error
                      // tracking fingerprints on message text, so keeping the rotating
                      // timestamp spawned a brand-new issue every 5-minute bucket. The
                      // full href is preserved as an exception property for debugging.
                      const hrefWithoutCacheBuster = href.split('?')[0]
                      toolbarLogger.error('config', 'Failed to load toolbar.css', { href })
                      captureToolbarException(
                          new Error(`Failed to load toolbar.css from ${hrefWithoutCacheBuster}`),
                          'toolbar_css_load',
                          { href }
                      )
                      toolbarPosthogJS.capture('toolbar css load failed', { href })
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
