import React, { useRef } from 'react'
import { useSecondRender } from 'lib/hooks/useSecondRender'
import root from 'react-shadow'
import { ToolbarContainer } from '~/toolbar/ToolbarContainer'
import { useMountedLogic } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { EditorProps } from '~/types'
import { Slide, ToastContainer } from 'react-toastify'

type HTMLElementWithShadowRoot = HTMLElement & { shadowRoot: ShadowRoot }

export function ToolbarApp(props: EditorProps = {}): JSX.Element {
    useMountedLogic(toolbarLogic(props))

    const shadowRef = useRef<HTMLElementWithShadowRoot | null>(null)

    // this runs after the shadow root has been added to the dom
    const didRender = useSecondRender(() => {
        function addStyleElementToShadowRoot(element: HTMLElement): void {
            const shadowRoot =
                shadowRef.current?.shadowRoot || window.document.getElementById('__POSTHOG_TOOLBAR__')?.shadowRoot
            shadowRoot?.getElementById('posthog-toolbar-styles')?.appendChild(element)
        }

        // add styles that webpack has rendered until now
        const styles = ((window as any)['__PHGTLB_STYLES__'] || []) as unknown as HTMLStyleElement[]
        if (styles) {
            styles.forEach((element) => addStyleElementToShadowRoot(element))
        }

        // add function to render styles in the future
        ;(window as any)['__PHGTLB_ADD_STYLES__'] = (element: HTMLStyleElement) => addStyleElementToShadowRoot(element)
    })

    return (
        <>
            <root.div id="__POSTHOG_TOOLBAR__" className="ph-no-capture" ref={shadowRef}>
                <div id="posthog-toolbar-styles" />
                {didRender ? <ToolbarContainer /> : null}
                <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
            </root.div>
        </>
    )
}
