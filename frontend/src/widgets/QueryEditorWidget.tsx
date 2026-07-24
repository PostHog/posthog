import { useValues } from 'kea'
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import root from 'react-shadow'

import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, Node } from '~/queries/schema/schema-general'

import { WidgetInstanceStore } from './widgetStore'

type HTMLElementWithShadowRoot = HTMLElement & { shadowRoot: ShadowRoot }

/** Where the widget bundle was loaded from — used to locate the sibling widgets.css. */
let assetBaseUrl: string | null = null
export function setWidgetAssetBaseUrl(url: string): void {
    assetBaseUrl = url
}

function useShadowStyles(shadowHost: HTMLElementWithShadowRoot | null): boolean {
    const [didLoadStyles, setDidLoadStyles] = useState(false)

    useEffect(() => {
        // Runs once the shadow root is attached. Mirrors ToolbarApp.tsx: the app CSS is
        // built as a sibling file next to the JS bundle and linked into the shadow root.
        const shadowRoot = shadowHost?.shadowRoot
        if (!shadowRoot) {
            return
        }
        const styleLink = document.createElement('link')
        styleLink.rel = 'stylesheet'
        styleLink.type = 'text/css'
        styleLink.href = assetBaseUrl ? `${assetBaseUrl}widgets.css` : 'widgets.css'
        styleLink.onload = () => setDidLoadStyles(true)
        styleLink.onerror = () => {
            // Render anyway — unstyled beats invisible, and it surfaces the misconfiguration.
            console.warn('[PostHogWidgets] Failed to load widgets.css from', styleLink.href)
            setDidLoadStyles(true)
        }
        shadowRoot.appendChild(styleLink)
        return () => {
            styleLink.remove()
        }
    }, [shadowHost])

    return didLoadStyles
}

/** Renders the editable Query component once the global logics have hydrated. */
function QueryEditorBody({ store }: { store: WidgetInstanceStore }): JSX.Element {
    const state = useSyncExternalStore(store.subscribe, store.get)
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)

    const query = state.query as Node

    const setQuery = useMemo(() => {
        return (nextQuery: Node) => {
            // Round-trip through JSON so hosts always receive plain serializable data.
            const plain = JSON.parse(JSON.stringify(nextQuery))
            store.setQuery(plain)
            store.get().onQueryChange?.(plain)
        }
    }, [store])

    if (!user || !currentTeam) {
        return (
            <div className="flex items-center justify-center p-8 gap-2 text-secondary">
                <Spinner />
                <span>Connecting to PostHog…</span>
            </div>
        )
    }

    return (
        <Query<InsightVizNode>
            query={query as InsightVizNode}
            setQuery={setQuery as (query: InsightVizNode, isSourceUpdate?: boolean) => void}
            readOnly={false}
            editMode
        />
    )
}

export function QueryEditorWidget({ store }: { store: WidgetInstanceStore }): JSX.Element {
    const state = useSyncExternalStore(store.subscribe, store.get)
    const [shadowHost, setShadowHost] = useState<HTMLElementWithShadowRoot | null>(null)
    const didLoadStyles = useShadowStyles(shadowHost)
    const [floatingContainer, setFloatingContainer] = useState<HTMLDivElement | null>(null)

    // The `theme` attribute drives PostHog's dark-mode CSS ([theme='dark'] selectors).
    // It must live INSIDE the shadow root — an attribute on the outer document does not
    // penetrate the shadow boundary.
    const themeProps = { theme: state.theme }

    return (
        <root.div id="posthog-widgets-query-editor" ref={setShadowHost as any} mode="open">
            {shadowHost && didLoadStyles ? (
                <FloatingContainerContext.Provider value={floatingContainer}>
                    <div
                        {...themeProps}
                        className="posthog-widget-frame bg-primary text-primary"
                        style={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}
                    >
                        <QueryEditorBody store={store} />
                        {/* Popovers, tooltips and modals portal here so they stay inside the shadow root. */}
                        <div
                            ref={setFloatingContainer}
                            {...themeProps}
                            className="fixed inset-0 pointer-events-none z-[2147483000] [&>*]:pointer-events-auto"
                        />
                    </div>
                </FloatingContainerContext.Provider>
            ) : null}
        </root.div>
    )
}
