import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconGear, IconPlusSmall, IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { FileSystemEntry, FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { getCustomIcon } from '../../ProjectTree/customIconRegistry'
import { ProductIconWrapper, iconForType } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { joinPath, splitPath } from '../../ProjectTree/utils'
import { appsItemName } from './appsCatalog'
import { NavAppMenu } from './NavAppMenu'

export function NavAppRow({ item }: { item: FileSystemImport }): JSX.Element {
    const { pathname } = useValues(panelLayoutLogic)
    const { shortcutData, shortcutDataLoading } = useValues(projectTreeDataLogic)
    const { addShortcutItem, deleteShortcut } = useActions(projectTreeDataLogic)
    const { reportNavItemClicked } = useActions(eventUsageLogic)
    const { showConfigureHomeModal } = useActions(navigationLogic)
    const { uiCustomizationEnabled } = useValues(uiCustomizationLogic)
    const label = appsItemName(item)
    const shortcutPath = joinPath([splitPath(item.path).pop() ?? 'Unnamed'])
    const shortcut = shortcutData.find((entry) => entry.type !== 'folder' && entry.path === shortcutPath)
    const currentPath = removeProjectIdIfPresent(pathname)
    const href = item.href ?? ''
    const active =
        currentPath === href ||
        (href !== urls.projectRoot() && currentPath.startsWith(`${href}/`)) ||
        (href === urls.projectRoot() && currentPath === urls.projectHomepage()) ||
        (item.path === 'Session replay' && currentPath.startsWith('/replay/'))
    const disabledReason = getProductAccessDisabledReason(item)
    const CustomIcon = getCustomIcon(item.type)
    const iconType = item.iconType ?? (item.type as FileSystemIconType | undefined)

    return (
        <div className="group/app-row flex items-center gap-px min-w-0">
            <Link
                to={disabledReason ? undefined : href}
                disabledReason={disabledReason}
                buttonProps={{
                    menuItem: true,
                    active,
                    disabled: !!disabledReason,
                    className: 'flex-1 min-w-0 -outline-offset-2',
                }}
                data-attr="nav-apps-item"
                tooltip={label}
                tooltipPlacement="right"
                onClick={() => reportNavItemClicked(item.path, 'tools')}
            >
                <span className="size-4 shrink-0">
                    {CustomIcon ? (
                        <ProductIconWrapper type={iconType} colorOverride={item.iconColor}>
                            <CustomIcon />
                        </ProductIconWrapper>
                    ) : (
                        iconForType(iconType, item.iconColor)
                    )}
                </span>
                <span className="flex-1 truncate">{label}</span>
                {item.tags?.[0] && (
                    <LemonTag type={item.tags[0] === 'alpha' ? 'completion' : 'warning'} size="small">
                        {item.tags[0]}
                    </LemonTag>
                )}
            </Link>
            {!disabledReason && ['Product analytics', 'Dashboards', 'Session replay'].includes(item.path) && (
                <LemonMenu placement="right-start" items={[{ label: () => <NavAppMenu product={item.path} /> }]}>
                    <LemonButton
                        size="xsmall"
                        icon={item.path === 'Product analytics' ? <IconPlusSmall /> : <IconChevronDown />}
                        tooltip={
                            item.path === 'Product analytics'
                                ? 'New insight'
                                : item.path === 'Dashboards'
                                  ? 'Pinned dashboards'
                                  : 'Saved filters and collections'
                        }
                        aria-label={`Open ${label} menu`}
                        data-attr={
                            item.path === 'Product analytics'
                                ? 'flat-nav-tool-menu-insight'
                                : item.path === 'Dashboards'
                                  ? 'flat-nav-tool-menu-dashboards'
                                  : 'flat-nav-tool-menu-session-replay'
                        }
                    />
                </LemonMenu>
            )}
            {item.path === 'Home' && (
                <LemonButton
                    size="xsmall"
                    icon={<IconGear />}
                    tooltip="Configure home"
                    data-attr="nav-configure-home"
                    onClick={() => {
                        if (uiCustomizationEnabled) {
                            router.actions.push(urls.settings('user-navigation', 'homepage'))
                        } else {
                            showConfigureHomeModal()
                        }
                    }}
                />
            )}
            <LemonButton
                size="xsmall"
                icon={shortcut ? <IconStarFilled /> : <IconStar />}
                className={
                    shortcut
                        ? 'shrink-0'
                        : 'shrink-0 opacity-0 group-hover/app-row:opacity-100 focus-visible:opacity-100'
                }
                tooltip={shortcut ? 'Remove from starred' : 'Add to starred'}
                aria-label={`${shortcut ? 'Unstar' : 'Star'} ${label}`}
                data-attr="nav-apps-star"
                loading={shortcutDataLoading}
                disabledReason={disabledReason}
                onClick={() => (shortcut ? deleteShortcut(shortcut.id) : addShortcutItem(item as FileSystemEntry))}
            />
        </div>
    )
}
