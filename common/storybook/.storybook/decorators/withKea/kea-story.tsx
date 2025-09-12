import { createMemoryHistory } from 'history'
import { getContext } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { App } from 'scenes/App'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKea } from '~/initKea'
import { worker } from '~/mocks/browser'

export function resetKeaStory(): void {
    worker.resetHandlers()

    const history = createMemoryHistory({})
    ;(history as any).pushState = history.push
    ;(history as any).replaceState = history.replace
    initKea({ routerLocation: history.location, routerHistory: history, replaceInitialPathInWindow: false })
    featureFlagLogic.mount()
    teamLogic.mount()
    projectLogic.mount()
    userLogic.mount()
    router.mount()
    const { store } = getContext()
    store.dispatch({ type: 'storybook init' })
}

export function KeaStory<T = React.ReactNode>({ children }: { children: T }): T | JSX.Element | null {
    const [didReset, setDidReset] = useState(false)
    useEffect(() => {
        if (!didReset) {
            resetKeaStory()
            setDidReset(true)
        }
    }, [didReset])

    return didReset ? children || <App /> : null
}
