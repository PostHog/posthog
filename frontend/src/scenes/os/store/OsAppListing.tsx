import { useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { OsAppIcon } from '../icons/OsAppIcon'
import { OsAppActions } from './OsAppActions'
import { OS_JOB_TITLE, OsAppStatus } from './osAppCatalog'
import { osAppStoreSceneLogic } from './osAppStoreSceneLogic'
import { OsAppTags } from './OsAppTags'

const STATUS_TEXT: Record<OsAppStatus, string> = {
    released: 'Released',
    beta: 'Beta. It works, and it may still change.',
    alpha: 'Alpha. It is early, and parts of it may change or go away.',
    unreleased: 'Preview. Only people with early access see it.',
}

/** One app's page in the store. */
export function OsAppListing(): JSX.Element {
    const { selectedApp: app } = useValues(osAppStoreSceneLogic)

    return (
        <div className="flex max-w-200 flex-col gap-4">
            <Link
                to={urls.osAppStore()}
                className="inline-flex items-center gap-1 self-start"
                data-attr="os-app-store-back"
            >
                <IconArrowLeft />
                All apps
            </Link>
            {!app ? (
                <p className="text-secondary">
                    This app is not available to you. It may need early access, or you may not have access to it.
                </p>
            ) : (
                <article className="flex flex-col gap-4" data-attr="os-app-store-listing">
                    <header className="flex flex-wrap items-center gap-4">
                        <OsAppIcon app={app} size="large" />
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <h2 className="m-0 text-xl font-bold">{app.name}</h2>
                            <OsAppTags app={app} />
                        </div>
                        <OsAppActions app={app} showRemove size="medium" />
                    </header>
                    {app.description && <p className="m-0">{app.description}</p>}
                    <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
                        <dt className="text-secondary">Status</dt>
                        <dd className="m-0">{STATUS_TEXT[app.status]}</dd>
                        <dt className="text-secondary">Category</dt>
                        <dd className="m-0">{OS_JOB_TITLE[app.job]}</dd>
                    </dl>
                </article>
            )}
        </div>
    )
}
