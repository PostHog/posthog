import { createMemoryHistory } from 'history'
import { getContext } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { App } from 'scenes/App'
// Eagerly bring AuthenticatedShell into the storybook bundle. App.tsx code-splits
// it via React.lazy in production, but storybook tests render scenes outside the
// App tree where the lazy chunk would never load - and several scene stories rely
// on module-level side effects from imports inside the shell (kea connect chains,
// CSS, decorators) being present at evaluation time.
import 'scenes/AuthenticatedShell'
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
