import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconX } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { LinkListItem } from 'lib/ui/LinkListItem/LinkListItem'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { BrowserLikeMenuItems } from '~/layout/panel-layout/ProjectTree/menus/BrowserLikeMenuItems'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { FileSystemEntry, FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { AppsItemGroup, appsItemName, navAppsTabLogic } from './navAppsTabLogic'
import { AddToStarredDropdownAction } from './NavTabBrowse'

/**
 * The desktop app's "Apps" navbar tab: a searchable combined list of tools and data items,
 * with the user's starred items on top. Starring uses the same file-system-shortcut backend
 * as the project tree, via the row's "..." menu.
 */

function AppsRow({
    href,
    name,
    icon,
    active,
    actions,
    tags,
}: {
    href: string
    name: string
    icon: JSX.Element
    active: boolean
    actions: JSX.Element
    tags?: ('alpha' | 'beta')[]
}): JSX.Element {
    return (
        <LinkListItem.Root>
            <LinkListItem.Group>
                <Link
                    to={href}
                    buttonProps={{
                        menuItem: true,
                        active,
                        className: 'group -outline-offset-2 pr-0',
                    }}
                    data-attr="nav-apps-item"
                >
                    <LinkListItem.Content
                        icon={icon}
                        title={name}
                        meta={
                            tags?.length ? (
                                <LemonTag type={tags.includes('alpha') ? 'completion' : 'warning'} size="small">
                                    {tags.includes('alpha') ? 'Alpha' : 'Beta'}
                                </LemonTag>
                            ) : undefined
                        }
                    />
                </Link>
                <LinkListItem.Trigger />
            </LinkListItem.Group>
            <LinkListItem.Actions>{actions}</LinkListItem.Actions>
        </LinkListItem.Root>
    )
}

function AppsSection({
    label,
    items,
    currentPath,
}: {
    label: string
    items: FileSystemImport[]
    currentPath: string
}): JSX.Element | null {
    if (items.length === 0) {
        return null
    }
    return (
        <>
            <div className="px-2 pt-2">
                <Label intent="menu" className="text-xxs text-secondary">
                    {label}
                </Label>
            </div>
            <div className="flex flex-col gap-px">
                {items.map((item: FileSystemImport) => (
                    <AppsRow
                        key={`${item.path}-${item.href}`}
                        href={item.href ?? '#'}
                        name={appsItemName(item)}
                        icon={iconForType(item.iconType, item.iconColor)}
                        active={!!item.href && currentPath === removeProjectIdIfPresent(item.href)}
                        tags={item.tags}
                        actions={<AddToStarredDropdownAction item={item as FileSystemEntry} />}
                    />
                ))}
            </div>
        </>
    )
}

export function NavTabApps(): JSX.Element {
    const { search, groupedItems, starredItems } = useValues(navAppsTabLogic)
    const { setSearch } = useActions(navAppsTabLogic)
    const { deleteShortcut } = useActions(projectTreeDataLogic)
    const { location } = useValues(router)
    const currentPath = removeProjectIdIfPresent(location.pathname)

    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="px-2 pt-2 pb-1">
                <LemonInput
                    type="search"
                    size="xsmall"
                    placeholder="Search apps"
                    value={search}
                    onChange={setSearch}
                    fullWidth
                    data-attr="nav-apps-search"
                />
            </div>

            <ScrollableShadows direction="vertical" className="flex-1 min-h-0" innerClassName="px-1 pb-2">
                {starredItems.length > 0 && (
                    <>
                        <div className="px-2 pt-2">
                            <Label intent="menu" className="text-xxs text-secondary">
                                Starred
                            </Label>
                        </div>
                        <div className="flex flex-col gap-px">
                            {starredItems.map((entry: FileSystemEntry) => (
                                <AppsRow
                                    key={entry.id}
                                    href={entry.href ?? '#'}
                                    name={appsItemName(entry)}
                                    icon={iconForType(entry.type as FileSystemIconType)}
                                    active={!!entry.href && currentPath === removeProjectIdIfPresent(entry.href)}
                                    actions={
                                        <DropdownMenuGroup>
                                            <BrowserLikeMenuItems MenuItem={DropdownMenuItem} href={entry.href ?? ''} />
                                            <DropdownMenuItem asChild>
                                                <ButtonPrimitive menuItem onClick={() => deleteShortcut(entry.id)}>
                                                    <IconX className="size-4 text-tertiary" />
                                                    Remove from starred
                                                </ButtonPrimitive>
                                            </DropdownMenuItem>
                                        </DropdownMenuGroup>
                                    }
                                />
                            ))}
                        </div>
                    </>
                )}

                {groupedItems.map((group: AppsItemGroup) => (
                    <AppsSection key={group.label} label={group.label} items={group.items} currentPath={currentPath} />
                ))}
                {groupedItems.length === 0 && starredItems.length === 0 && (
                    <span className="text-xs text-tertiary px-2 py-1">No results</span>
                )}
            </ScrollableShadows>
        </div>
    )
}
