import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { OsAppIcon } from '../icons/OsAppIcon'
import { OsAppActions } from './OsAppActions'
import type { OsApp } from './osAppCatalog'
import { OsAppTags } from './OsAppTags'

/** One app on the store front page. The name links to its listing. */
export function OsAppTile({ app }: { app: OsApp }): JSX.Element {
    return (
        <li
            className="flex gap-3 rounded-lg border border-primary bg-surface-primary p-3"
            data-attr="os-app-store-tile"
        >
            <OsAppIcon app={app} size="medium" />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <Link
                    to={urls.osAppStore(app.slug)}
                    className="truncate font-semibold text-primary"
                    data-attr={`os-app-store-tile-${app.slug}`}
                >
                    {app.name}
                </Link>
                <OsAppTags app={app} />
                {app.description && <p className="m-0 line-clamp-2 text-xs text-secondary">{app.description}</p>}
                <div className="mt-auto pt-1">
                    <OsAppActions app={app} />
                </div>
            </div>
        </li>
    )
}
