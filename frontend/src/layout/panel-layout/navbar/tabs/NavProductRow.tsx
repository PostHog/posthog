import { useActions, useValues } from 'kea'

import { IconChevronDown, IconGear, IconPlusSmall, IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu } from '@posthog/lemon-ui'

import { ProductTag } from 'lib/components/ProductTag/ProductTag'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { FileSystemEntry, FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { getCustomIcon } from '../../ProjectTree/customIconRegistry'
import { ProductIconWrapper, iconForType } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { joinPath, splitPath } from '../../ProjectTree/utils'
import { NavProductMenu } from './NavProductMenu'
import { navProductsTabLogic } from './navProductsTabLogic'
import { NavProductTooltip } from './NavProductTooltip'
import { productsItemName } from './productsCatalog'

export function NavProductRow({ item, pinned = false }: { item: FileSystemImport; pinned?: boolean }): JSX.Element {
    const { pathname } = useValues(panelLayoutLogic)
    const { resetPanelLayout } = useActions(panelLayoutLogic)
    const { shortcutData, shortcutDataLoading } = useValues(projectTreeDataLogic)
    const { addShortcutItem, deleteShortcut } = useActions(projectTreeDataLogic)
    const { reportNavItemClicked } = useActions(eventUsageLogic)
    const { setCustomizeSidebarOpen } = useActions(navProductsTabLogic)
    const label = productsItemName(item)
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

    const isHome = item.path === 'Home'
    const hasProductMenu = ['Product analytics', 'Dashboards', 'Session replay'].includes(item.path)
    const hasSideAction = isHome || !pinned
    const starAction = {
        label: shortcut ? 'Remove from starred' : 'Add to starred',
        icon: shortcut ? <IconStarFilled /> : <IconStar />,
        'data-attr': 'nav-apps-star',
        disabledReason: disabledReason || (shortcutDataLoading ? 'Updating starred items' : undefined),
        onClick: () => {
            if (!shortcut) {
                addShortcutItem(item as FileSystemEntry)
                return
            }
            LemonDialog.open({
                title: `Remove ${label} from starred?`,
                description: 'It will no longer appear in the starred section of the sidebar.',
                maxWidth: '30rem',
                primaryButton: {
                    children: 'Remove',
                    status: 'danger',
                    onClick: () => deleteShortcut(shortcut.id),
                    'data-attr': 'nav-apps-unstar-confirm',
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
    }
    const menuItems: LemonMenuItems = [{ label: () => <NavProductMenu product={item.path} /> }, { items: [starAction] }]
    // Appears at once like a tree row's side action, while keeping LemonButton's press animation.
    const sideActionClassName =
        'absolute right-0 opacity-0 group-hover/product-row:opacity-100 group-has-[:focus-visible]/product-row:opacity-100 [--lemon-button-transition:transform_200ms_ease]'

    return (
        <div className="group/product-row relative flex items-center gap-px min-w-0">
            <Tooltip title={disabledReason || <NavProductTooltip item={item} />} placement="right">
                <Link
                    to={disabledReason ? undefined : href}
                    disabledReason={disabledReason}
                    buttonProps={{
                        menuItem: true,
                        active,
                        disabled: !!disabledReason,
                        className: cn(
                            'flex-1 min-w-0 -outline-offset-2 motion-safe:transition-[padding] duration-50',
                            hasSideAction && 'group-hover/product-row:pr-7 group-has-[:focus-visible]/product-row:pr-7',
                            !pinned && !hasProductMenu && shortcut && 'pr-7'
                        ),
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
                    {item.tags?.[0] && <ProductTag tag={item.tags[0]} />}
                </Link>
            </Tooltip>
            {isHome ? (
                <LemonButton
                    size="xsmall"
                    className={sideActionClassName}
                    icon={<IconGear />}
                    tooltip="Customize sidebar"
                    aria-label="Customize sidebar"
                    onClick={() => setCustomizeSidebarOpen(true)}
                    data-attr="nav-customize-sidebar"
                />
            ) : pinned ? null : hasProductMenu ? (
                <LemonMenu placement="right-start" items={menuItems}>
                    <LemonButton
                        size="xsmall"
                        className={sideActionClassName}
                        icon={item.path === 'Product analytics' ? <IconPlusSmall /> : <IconChevronDown />}
                        tooltip={`Open ${label} menu`}
                        aria-label={`Open ${label} menu`}
                        disabledReason={disabledReason}
                        data-attr={
                            item.path === 'Product analytics'
                                ? 'flat-nav-tool-menu-insight'
                                : item.path === 'Dashboards'
                                  ? 'flat-nav-tool-menu-dashboards'
                                  : 'flat-nav-tool-menu-session-replay'
                        }
                    />
                </LemonMenu>
            ) : (
                <LemonButton
                    size="xsmall"
                    className={cn(sideActionClassName, shortcut && 'opacity-100')}
                    icon={starAction.icon}
                    tooltip={starAction.label}
                    aria-label={starAction.label}
                    disabledReason={starAction.disabledReason}
                    onClick={starAction.onClick}
                    data-attr={starAction['data-attr']}
                />
            )}
        </div>
    )
}
