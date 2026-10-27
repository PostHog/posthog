import '~/styles'

import '../buffer-polyfill'

import { Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'

import { RootErrorBoundary, reportBootFailure } from '../RootErrorBoundary'

performance.mark('auth-prototype:entry')

const modules = Promise.all([import('./AuthPrototype'), import('../initKea'), import('../loadPostHogJS')]).then(
    (loaded) => {
        performance.mark('auth-prototype:modules-loaded')
        return loaded
    }
)
void modules.catch(() => {})

const AuthPrototype = lazy(async () => {
    const [app, { initKea }, { loadPostHogJS }] = await modules
    loadPostHogJS()
    initKea({ replaceInitialPathInWindow: false })
    return { default: app.AuthPrototype }
})

async function renderAuthPrototype(): Promise<void> {
    const root = document.getElementById('root')
    if (!root) {
        return
    }

    const appRoot = createRoot(root)
    let timeout: ReturnType<typeof setTimeout> | undefined
    const stylesReady = await Promise.race([
        window.ESBUILD_CSS_READY ?? Promise.resolve(true),
        new Promise<boolean>((resolve) => {
            timeout = setTimeout(() => resolve(false), 5000)
        }),
    ])
    clearTimeout(timeout)
    const fallback = new URL(window.location.href)
    fallback.searchParams.set('auth_app', 'fallback')
    if (!stylesReady) {
        reportBootFailure(new Error('Login styles could not load'))
    }

    appRoot.render(
        stylesReady ? (
            <RootErrorBoundary fallbackHref={fallback.href}>
                <Suspense fallback={null}>
                    <AuthPrototype />
                </Suspense>
            </RootErrorBoundary>
        ) : (
            <div role="alert">
                Login styles could not load.{' '}
                {/* eslint-disable-next-line react/forbid-elements -- Recovery must work before the app router starts. */}
                <a href={fallback.href}>Open the standard login page</a> to try again.
            </div>
        )
    )
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => void renderAuthPrototype(), { once: true })
} else {
    void renderAuthPrototype()
}
