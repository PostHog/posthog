import { useValues } from 'kea'
import { useRef, useState } from 'react'
import root from 'react-shadow'
import { Slide, ToastContainer } from 'react-toastify'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useSecondRender } from 'lib/hooks/useSecondRender'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { ToolbarContainer } from '~/toolbar/ToolbarContainer'
import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarProps } from '~/types'

import { TOOLBAR_ID } from './utils'
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

                  // The stylesheet is the app entry's CSS, emitted as a hashless copy inside
                  // dist/toolbar/ next to the JS. It must be fetched from there — its url()
                  // references (fonts) are relative, so they only resolve alongside the
                  // toolbar/assets/ directory it was built with.
                  //
                  // The loader shares the origin it was served from as
                  // __POSTHOG_TOOLBAR_SCRIPT_SRC__. Resolve the CSS from that origin so it
                  // follows the same reverse proxy as the JS. The loader prefers this over the
                  // baked absolute CDN host for the same reason (see resolveAppUrl in loader.ts),
                  // and this is why a style-src 'self' CSP or an ad blocker no longer strips the
                  // stylesheet on proxied customer pages.
                  const scriptSrc = (window as any).__POSTHOG_TOOLBAR_SCRIPT_SRC__ as string | undefined

                  if (__POSTHOG_TOOLBAR_PUBLIC_PATH__) {
                      // posthog-js versioned bundle: the version in the path is the cache key, so
                      // no cache-busting query param is needed.
                      const base = scriptSrc || __POSTHOG_TOOLBAR_PUBLIC_PATH__
                      styleLink.href = new URL('toolbar/toolbar-app.css', base).href
                  } else {
                      // posthog/posthog's own deploy: the URL is unversioned, so add a 5-minute
                      // cache-buster.
                      const fiveMinutesInMillis = 5 * 60 * 1000
                      const timestampToNearestFiveMinutes =
                          Math.floor(Date.now() / fiveMinutesInMillis) * fiveMinutesInMillis
                      const base = scriptSrc || `${apiHost}/static/toolbar.js`
                      styleLink.href = new URL(`toolbar/toolbar-app.css?t=${timestampToNearestFiveMinutes}`, base).href
                  }

                  styleLink.onload = () => setDidLoadStyles(true)
                  // Without onerror the toolbar silently stays invisible when the
                  // CSS 404s (didLoadStyles never flips to true). That masks
                  // misconfigured apiHost / rejected URLs. A failed stylesheet
                  // request is expected on customer pages (ad blockers, offline,
                  // misconfigured hosts), so surface it via logger + telemetry -
                  // not error tracking - and render the toolbar anyway; missing
                  // styles is a worse UX than nothing.
                  styleLink.onerror = () => {
                      toolbarLogger.error('config', 'Failed to load toolbar.css', { href: styleLink.href })
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
