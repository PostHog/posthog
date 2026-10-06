import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'
import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import { fileSystemBaseType, fileSystemEntryName, isAnalyticsType } from 'scenes/analytics/analyticsUtils'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

/** Each folder level steps in by this much, in Tailwind spacing units. */
const INDENT_CLASS = 'ps-4'

function folderChildren(entries: FileSystemEntry[] | undefined): FileSystemEntry[] {
    return (entries ?? [])
        .filter((entry) => entry.type === 'folder' || isAnalyticsType(fileSystemBaseType(entry.type)))
        .sort((first, second) => {
            if ((first.type === 'folder') !== (second.type === 'folder')) {
                return first.type === 'folder' ? -1 : 1
            }
            return fileSystemEntryName(first).localeCompare(fileSystemEntryName(second))
        })
}

function FolderNode({ entry, dataAttr }: { entry: FileSystemEntry; dataAttr: string }): JSX.Element {
    const { loadFolder } = useActions(projectTreeDataLogic)
    const name = fileSystemEntryName(entry)
    return (
        <Collapsible
            variant="folder"
            onOpenChange={(open: boolean) => {
                if (open) {
                    loadFolder(entry.path)
                }
            }}
        >
            <CollapsibleHeader>
                <CollapsibleTrigger iconOnly icon={<IconFolder />}>
                    {`Toggle ${name}`}
                </CollapsibleTrigger>
                <Button
                    variant="default"
                    size="sm"
                    left
                    nativeButton={false}
                    className="w-full min-w-0 ps-6 text-foreground"
                    render={<LinkPrimitive to={urls.analyticsList({ folder: entry.path })} />}
                    data-attr={`${dataAttr}-folder`}
                >
                    <span className="truncate">{name}</span>
                </Button>
            </CollapsibleHeader>
            <CollapsibleContent className={INDENT_CLASS}>
                <FolderChildren folder={entry.path} dataAttr={dataAttr} />
            </CollapsibleContent>
        </Collapsible>
    )
}

function FolderChildren({ folder, dataAttr }: { folder: string; dataAttr: string }): JSX.Element {
    const { folders, folderStates } = useValues(projectTreeDataLogic)
    const { loadFolder } = useActions(projectTreeDataLogic)
    const state = folderStates[folder]
    const children = folderChildren(folders[folder])

    if (state === 'error') {
        return (
            <div className="flex flex-col items-start gap-1 px-2 py-1">
                <Text size="xs" variant="muted">
                    This folder didn’t load.
                </Text>
                <Button
                    variant="outline"
                    size="xs"
                    onClick={() => loadFolder(folder, true)}
                    data-attr={`${dataAttr}-retry`}
                >
                    Try again
                </Button>
            </div>
        )
    }
    if (!folders[folder] && (state === 'loading' || state === undefined)) {
        return (
            <div className="flex flex-col gap-1 px-2 py-1" aria-busy>
                <Skeleton className="h-3 w-32" />
                <Skeleton className="h-3 w-24" />
            </div>
        )
    }
    if (!children.length) {
        return (
            <Text size="xs" variant="muted" className="block px-2 py-1">
                No analytics in this folder.
            </Text>
        )
    }
    return (
        <>
            {children.map((entry) => {
                if (entry.type === 'folder') {
                    return <FolderNode key={entry.id} entry={entry} dataAttr={dataAttr} />
                }
                const type = fileSystemBaseType(entry.type)
                return (
                    <Button
                        key={entry.id}
                        variant="default"
                        size="sm"
                        left
                        nativeButton={false}
                        className="w-full min-w-0 text-foreground"
                        render={<LinkPrimitive to={entry.href ?? urls.analyticsList()} />}
                        data-attr={`${dataAttr}-item`}
                    >
                        {isAnalyticsType(type) && (
                            <span
                                className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4"
                                aria-hidden
                            >
                                <AnalyticsTypeIcon type={type} />
                            </span>
                        )}
                        <span className="truncate">{fileSystemEntryName(entry)}</span>
                    </Button>
                )
            })}
        </>
    )
}

/** The project's folders, narrowed to the analytics in them. Folders load as they open. */
export function TodayAnalyticsFolderTree({ dataAttr }: { dataAttr: string }): JSX.Element {
    return <FolderChildren folder="" dataAttr={dataAttr} />
}
