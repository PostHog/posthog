import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconEllipsis, IconGear, IconPlusSmall, IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
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
import { NavAppTooltip } from './NavAppTooltip'

export function NavAppRow({ item }: { item: FileSystemImport }): JSX.Element {
    const { pathname } = useValues(panelLayoutLogic)
    const { resetPanelLayout } = useActions(panelLayoutLogic)
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
    const CustomIcon = getCustomIcon(item.type, item.href)
    const iconType = item.iconType ?? (item.type as FileSystemIconType | undefined)

    const hasProductMenu = ['Product analytics', 'Dashboards', 'Session replay'].includes(item.path)
    const menuItems: LemonMenuItems = [
        ...(hasProductMenu ? [{ label: () => <NavAppMenu product={item.path} /> }] : []),
        ...(item.path === 'Home'
            ? [
                  {
                      items: [
                          {
                              label: 'Configure home',
                              icon: <IconGear />,
                              'data-attr': 'nav-configure-home',
                              onClick: () => {
                                  if (uiCustomizationEnabled) {
                                      router.actions.push(urls.settings('user-navigation', 'homepage'))
                                  } else {
                                      showConfigureHomeModal()
                                  }
                              },
                          },
                      ],
                  },
              ]
            : []),
        {
            items: [
                {
                    label: shortcut ? 'Remove from starred' : 'Add to starred',
                    icon: shortcut ? <IconStarFilled /> : <IconStar />,
                    'data-attr': 'nav-apps-star',
                    disabledReason: disabledReason || (shortcutDataLoading ? 'Updating starred items' : undefined),
                    onClick: () => (shortcut ? deleteShortcut(shortcut.id) : addShortcutItem(item as FileSystemEntry)),
                },
            ],
        },
    ]

    return (
        <div className="group/app-row relative flex items-center gap-px min-w-0">
            <Tooltip title={disabledReason || <NavAppTooltip item={item} />} placement="right">
                <Link
                    to={disabledReason ? undefined : href}
                    disabledReason={disabledReason}
                    buttonProps={{
                        menuItem: true,
                        active,
                        disabled: !!disabledReason,
                        className:
                            'flex-1 min-w-0 -outline-offset-2 group-hover/app-row:pr-7 group-focus-within/app-row:pr-7',
                    }}
                    data-attr="nav-apps-item"
                    onClick={() => {
                        reportNavItemClicked(item.path, 'tools')
                        resetPanelLayout(false)
                    }}
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
            </Tooltip>
            <LemonMenu placement="right-start" items={menuItems}>
                <LemonButton
                    size="xsmall"
                    className="absolute right-0 opacity-0 group-hover/app-row:opacity-100 group-focus-within/app-row:opacity-100"
                    icon={
                        hasProductMenu ? (
                            item.path === 'Product analytics' ? (
                                <IconPlusSmall />
                            ) : (
                                <IconChevronDown />
                            )
                        ) : (
                            <IconEllipsis />
                        )
                    }
                    tooltip={`Open ${label} menu`}
                    aria-label={`Open ${label} menu`}
                    disabledReason={disabledReason}
                    data-attr={
                        item.path === 'Product analytics'
                            ? 'flat-nav-tool-menu-insight'
                            : item.path === 'Dashboards'
                              ? 'flat-nav-tool-menu-dashboards'
                              : item.path === 'Session replay'
                                ? 'flat-nav-tool-menu-session-replay'
                                : 'nav-apps-menu'
                    }
                />
            </LemonMenu>
        </div>
    )
}
