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
    // A record route can carry more segments than the record URL, such as `/insights/<short id>/edit`
    // or the canonical `/workflows/<id>/workflow`, and `urlToResource` answers for the record URL
    // alone. Ask about each prefix, so that a trailing segment does not hide the record.
    const parts = pathname.split('/').filter(Boolean)
    const namesRecord = parts.some((_, index) => !!urlToResource(parts.slice(0, index + 1).join('/')))
    return namesRecord || RECORD_SCENE_ROOTS.has(pathname.split('/')[1])
}
