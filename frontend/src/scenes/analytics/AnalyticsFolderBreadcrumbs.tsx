import { IconChevronRight, IconFolder } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { FolderRow } from './analyticsListLogic'

export function AnalyticsFolderBreadcrumbs({ crumbs }: { crumbs: FolderRow[] }): JSX.Element {
    return (
        <nav aria-label="Folder" className="flex flex-wrap items-center gap-1 text-sm">
            <Button
                variant="link-muted"
                size="sm"
                nativeButton={false}
                render={<LinkPrimitive to={urls.analyticsList({ folder: '' })} />}
                data-attr="analytics-list-folder-root"
            >
                <IconFolder />
                Project
            </Button>
            {crumbs.map((crumb, index) => (
                <span key={crumb.path} className="flex items-center gap-1">
                    <IconChevronRight className="size-3 text-muted-foreground" aria-hidden />
                    {index === crumbs.length - 1 ? (
                        <Text size="sm" className="font-semibold">
                            {crumb.name}
                        </Text>
                    ) : (
                        <Button
                            variant="link-muted"
                            size="sm"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.analyticsList({ folder: crumb.path })} />}
                            data-attr="analytics-list-folder-crumb"
                        >
                            {crumb.name}
                        </Button>
                    )}
                </span>
            ))}
        </nav>
    )
}
