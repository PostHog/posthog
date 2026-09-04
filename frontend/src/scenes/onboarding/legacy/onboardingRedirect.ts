import { removeProjectIdIfPresent, stripTrailingSlash } from 'lib/utils/kea-router'
import { routes } from 'scenes/scenes'
import { urlToResource } from 'scenes/urls'

// Scene roots that `urlToResource` cannot resolve, because the record behind them has no file
// system type: `/replay/<id>`, `/error_tracking/<issue id>`, `/person/<distinct id>`.
const RECORD_SCENE_ROOTS = new Set(['error_tracking', 'llm-analytics', 'person', 'replay', 'sessions'])

const STATIC_ROUTES = new Set(Object.keys(routes).filter((route) => !route.includes(':') && !route.includes('*')))

/**
 * True when the path names one record that belongs to a single project, such as a session
 * recording or an insight. Onboarding captures its redirect target before the project exists, so
 * such a target always points at a record the new project cannot own.
 */
export function pointsToRecordOfAnotherProject(path: string): boolean {
    const pathname = stripTrailingSlash(removeProjectIdIfPresent(path.split(/[?#]/)[0]))
    if (STATIC_ROUTES.has(pathname)) {
        return false
    }
    return !!urlToResource(pathname) || RECORD_SCENE_ROOTS.has(pathname.split('/')[1])
}
