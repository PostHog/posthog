import { patch } from '~/toolbar/core/patch'

export function makeNavigateWrapper(onNavigate: () => void, patchKey: string): () => () => void {
    return () => {
        let unwrapPushState: undefined | (() => void)
        let unwrapReplaceState: undefined | (() => void)
        if (!(window.history.pushState as any)?.[patchKey]) {
            unwrapPushState = patch(
                window.history,
                'pushState',
                (originalPushState) => {
                    return function patchedPushState(
                        this: History,
                        state: any,
                        title: string,
                        url?: string | URL | null
                    ): void {
                        ;(originalPushState as History['pushState']).call(this, state, title, url)
                        onNavigate()
                    }
                },
                patchKey
            )
        }

        if (!(window.history.replaceState as any)?.[patchKey]) {
            unwrapReplaceState = patch(
                window.history,
                'replaceState',
                (originalReplaceState) => {
                    return function patchedReplaceState(
                        this: History,
                        state: any,
                        title: string,
                        url?: string | URL | null
                    ): void {
                        ;(originalReplaceState as History['replaceState']).call(this, state, title, url)
                        onNavigate()
                    }
                },
                patchKey
            )
        }

        return () => {
            unwrapPushState?.()
            unwrapReplaceState?.()
        }
    }
}
