import { useValues } from 'kea'

import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import type { OsApp, OsAppStatus } from './osAppCatalog'
import { osAppStoreSceneLogic } from './osAppStoreSceneLogic'

const STATUS_TAGS: Record<Exclude<OsAppStatus, 'released'>, { label: string; type: LemonTagType }> = {
    beta: { label: 'Beta', type: 'warning' },
    alpha: { label: 'Alpha', type: 'completion' },
    unreleased: { label: 'Preview', type: 'caution' },
}

/** The app's release status, and whether it is installed. A released app shows no status tag. */
export function OsAppTags({ app }: { app: OsApp }): JSX.Element | null {
    const { installedKeys } = useValues(osAppStoreSceneLogic)
    const status = app.status === 'released' ? null : STATUS_TAGS[app.status]
    const installed = installedKeys.has(app.key) ? 'Installed' : null

    if (!status && !installed) {
        return null
    }
    return (
        <span className="flex flex-wrap items-center gap-1">
            {status && (
                <LemonTag type={status.type} size="small">
                    {status.label}
                </LemonTag>
            )}
            {installed && (
                <LemonTag type="success" size="small">
                    {installed}
                </LemonTag>
            )}
        </span>
    )
}
