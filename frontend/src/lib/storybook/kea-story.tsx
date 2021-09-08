import { createMemoryHistory } from 'history'
import { initKea } from '~/initKea'
import { router } from 'kea-router'
import { getContext, Provider } from 'kea'
import React, { useEffect, useState } from 'react'
import { App } from 'scenes/App'

function resetKeaWithState(state: Record<string, any>): void {
    const history = createMemoryHistory({ initialEntries: [state.kea.router.location] })
    initKea({ state, routerLocation: history.location, routerHistory: history })
    router.mount()
    const { store } = getContext()
    store.dispatch({ type: 'bla' })
}

export function KeaStory<T = React.ReactNode>({
    state,
    children,
}: {
    state: Record<string, any>
    children: T
}): T | JSX.Element | null {
    const [lastState, setLastState] = useState(null as Record<string, any> | null)

    useEffect(() => {
        if (state !== lastState) {
            setLastState(null)
        }
        if (state && lastState === null) {
            resetKeaWithState(state)
            setLastState(state)
        }
    }, [state])

    return lastState ? <Provider>{children || <App />}</Provider> : null
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
