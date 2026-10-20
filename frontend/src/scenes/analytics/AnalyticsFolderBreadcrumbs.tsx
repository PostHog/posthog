import { IconChevronRight, IconFolder } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { AnalyticsFolderDropTarget } from './AnalyticsFolderDropTarget'
import { FolderRow } from './analyticsListLogic'

export function AnalyticsFolderBreadcrumbs({ crumbs }: { crumbs: FolderRow[] }): JSX.Element {
    return (
        <nav aria-label="Collection" className="flex flex-wrap items-center gap-1 text-sm">
            <Button
                variant="link-muted"
                size="sm"
                nativeButton={false}
                render={<LinkPrimitive to={urls.analyticsSpaces()} />}
                data-attr="analytics-list-folder-root"
            >
                <IconFolder />
                Collections
            </Button>
            {crumbs.map((crumb, index) => (
                <span key={crumb.path} className="flex items-center gap-1">
                    <IconChevronRight className="size-3 text-muted-foreground" aria-hidden />
                    {index === crumbs.length - 1 ? (
                        <Text size="sm" className="font-semibold">
                            {crumb.name}
                        </Text>
                    ) : (
                        // A parent crumb takes dropped rows, which is how an item moves back out of a folder.
                        <AnalyticsFolderDropTarget path={crumb.path}>
                            <Button
                                variant="link-muted"
                                size="sm"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.analyticsList({ folder: crumb.path })} />}
                                data-attr="analytics-list-folder-crumb"
                            >
                                {crumb.name}
                            </Button>
                        </AnalyticsFolderDropTarget>
                    )}
                </span>
            ))}
        </nav>
    )
}
