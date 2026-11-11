import { useActions, useValues } from 'kea'

import { IconGear, IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { findProductShortcut } from '../../ProjectTree/utils'
import { sidebarProductMeta } from '../../sidebarProductMeta'
import { NavProductIcon } from './NavProductIcon'
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
    const shortcut = findProductShortcut(item, shortcutData)
    const currentPath = removeProjectIdIfPresent(pathname)
    const href = item.href ?? ''
    const active =
        currentPath === href ||
        (href !== urls.projectRoot() && currentPath.startsWith(`${href}/`)) ||
        (href === urls.projectRoot() && currentPath === urls.projectHomepage()) ||
        (item.path === 'Session replay' && currentPath.startsWith('/replay/'))
    const disabledReason = getProductAccessDisabledReason(item)

    const isHome = item.path === 'Home'
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
    // Appears at once like a tree row's side action, while keeping LemonButton's press animation.
    const sideActionClassName =
        'absolute right-0 opacity-0 group-hover/product-row:opacity-100 group-has-[:focus-visible]/product-row:opacity-100 [--lemon-button-transition:transform_200ms_ease]'

    return (
        <Tooltip
            title={disabledReason || <NavProductTooltip item={item} />}
            docLink={disabledReason ? undefined : sidebarProductMeta(item).docsHref}
            placement="right"
        >
            <div className="group/product-row relative flex items-center gap-px min-w-0">
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
                            !pinned && shortcut && 'pr-7'
                        ),
                    }}
                    data-attr="nav-apps-item"
                    onClick={() => {
                        reportNavItemClicked(item.path, 'tools')
                        resetPanelLayout(false)
                    }}
                >
                    <span className="size-4 shrink-0">
                        <NavProductIcon item={item} />
                    </span>
                    <span className="flex-1 truncate">{label}</span>
                </Link>
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
                ) : pinned ? null : (
                    <LemonButton
                        size="xsmall"
                        className={cn(sideActionClassName, shortcut && 'opacity-100')}
                        icon={starAction.icon}
                        aria-label={starAction.label}
                        disabledReason={starAction.disabledReason}
                        onClick={starAction.onClick}
                        data-attr={starAction['data-attr']}
                    />
                )}
            </div>
        </Tooltip>
    )
}
