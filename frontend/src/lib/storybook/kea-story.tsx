import { createMemoryHistory } from 'history'
import { initKea } from '~/initKea'
import { combineUrl, router } from 'kea-router'
import { getContext, Provider } from 'kea'
import React, { useEffect, useState } from 'react'
import { App } from 'scenes/App'
import { featureFlagLogic } from '../logic/featureFlagLogic'
import { systemStatusLogic } from '../../scenes/instance/SystemStatus/systemStatusLogic'

export function resetKeaStory(url?: string, state?: Record<string, any>): void {
    const initialLocation = url ? combineUrl(url) : state?.kea?.router?.location
    const history = createMemoryHistory(initialLocation ? { initialEntries: [initialLocation] } : {})
    ;(history as any).pushState = history.push
    ;(history as any).replaceState = history.replace
    initKea({ state, routerLocation: history.location, routerHistory: history })
    featureFlagLogic.mount()
    systemStatusLogic.mount()
    router.mount()
    const { store } = getContext()
    store.dispatch({ type: 'storybook init' })
}

export function KeaStory<T = React.ReactNode>({
    url,
    state,
    onInit,
    children,
}: {
    url?: string
    state?: Record<string, any>
    onInit?: () => void
    children: T
}): T | JSX.Element | null {
    const [didReset, setDidReset] = useState(false)
    useEffect(() => {
        if (!didReset) {
            resetKeaStory(url, state)
            onInit?.()
            setDidReset(true)
        }
    }, [didReset])

    return didReset ? <Provider>{children || <App />}</Provider> : null
}

export function keaStory(Component: any, json: any): () => JSX.Element {
    return function KeaStoryInstance() {
        return (
            <KeaStory state={json}>
                <Component />
            </KeaStory>
        )
    }
}
