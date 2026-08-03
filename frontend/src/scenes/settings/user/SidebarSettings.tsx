import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonLabel, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonColorPicker } from 'lib/lemon-ui/LemonColor/LemonColorPicker'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { PRODUCT_BRANDING } from 'scenes/welcome/productBranding'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { getDefaultTreeProducts, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { PRODUCTS_SHOWN_WITH_SELECTED_PRODUCTS } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { getCategoryOrder } from '~/layout/panel-layout/ProjectTree/utils'
import {
    DEFAULT_SIDEBAR_ITEM_ORDER,
    SIDEBAR_CUSTOMIZABLE_FOOTER_ITEMS,
    SIDEBAR_CUSTOMIZABLE_SECTIONS,
    SIDEBAR_PRESETS,
    SidebarCustomizableItem,
} from '~/layout/panel-layout/sidebarCustomization'
import { HomepageConfiguration } from '~/layout/scenes/HomepageConfiguration'
import { orderKeys, uiCustomizationLogic, withKeyMovedAmong } from '~/layout/uiCustomizationLogic'
import { productConfiguration } from '~/products'
import { FileSystemImport, SidebarDensity } from '~/queries/schema/schema-general'

/** Curated accent swatches: PostHog's brand hues plus a few colors that read well in both themes. */
const ACCENT_COLOR_SWATCHES = ['#f54e00', '#1d4aff', '#f9bd2b', '#029960', '#621da6', '#30abc6', '#df4313', '#94a4b5']

export function HomepageSetting(): JSX.Element {
    return (
        <div className="max-w-160">
            <HomepageConfiguration />
        </div>
    )
}

function ItemLabel({
    icon,
    label,
    description,
    docsHref,
}: {
    icon: JSX.Element
    label: string
    description?: string
    docsHref?: string
}): JSX.Element {
    return (
        <span className="flex items-center gap-2">
            <span className="text-lg text-secondary flex items-center">{icon}</span>
            <span className="flex flex-col">
                <span className="flex items-center gap-2">
                    {label}
                    {docsHref && (
                        <Link
                            to={docsHref}
                            target="_blank"
                            className="text-xs font-normal"
                            onClick={(e) => e.stopPropagation()}
                        >
                            Docs
                        </Link>
                    )}
                </span>
                {description && <span className="text-xs font-normal text-secondary">{description}</span>}
            </span>
        </span>
    )
}

function MoveButtons({
    canMoveUp,
    canMoveDown,
    onMove,
    dataAttrPrefix,
}: {
    canMoveUp: boolean
    canMoveDown: boolean
    onMove: (direction: 1 | -1) => void
    dataAttrPrefix: string
}): JSX.Element {
    return (
        <div className="flex flex-col justify-center">
            <LemonButton
                size="xsmall"
                icon={<IconArrowUp />}
                disabledReason={canMoveUp ? undefined : 'Already first'}
                onClick={() => onMove(-1)}
                tooltip="Move up"
                data-attr={`${dataAttrPrefix}-move-up`}
            />
            <LemonButton
                size="xsmall"
                icon={<IconArrowDown />}
                disabledReason={canMoveDown ? undefined : 'Already last'}
                onClick={() => onMove(1)}
                tooltip="Move down"
                data-attr={`${dataAttrPrefix}-move-down`}
            />
        </div>
    )
}

export function SidebarPresetsSetting(): JSX.Element {
    const { projectDefaultUiConfiguration, userLoading } = useValues(uiCustomizationLogic)
    const { applySidebarConfiguration, resetUiConfiguration } = useActions(uiCustomizationLogic)

    return (
        <div className="flex flex-col gap-2 max-w-160">
            {SIDEBAR_PRESETS.map((preset) => (
                <div
                    key={preset.key}
                    className="flex items-center justify-between gap-2 border rounded p-3"
                    data-attr={`sidebar-preset-${preset.key}`}
                >
                    <span className="flex flex-col">
                        <span>{preset.label}</span>
                        <span className="text-xs text-secondary">{preset.description}</span>
                    </span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={userLoading}
                        onClick={() =>
                            LemonDialog.open({
                                title: `Apply the ${preset.label} preset?`,
                                description:
                                    'This replaces your current sidebar layout, including item order and pinned groups. Accent colors are kept.',
                                primaryButton: {
                                    children: 'Apply preset',
                                    onClick: () => applySidebarConfiguration(preset.sidebar, preset.key),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                        data-attr={`sidebar-preset-apply-${preset.key}`}
                    >
                        Apply
                    </LemonButton>
                </div>
            ))}
            <div className="flex gap-2">
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    loading={userLoading}
                    onClick={() =>
                        LemonDialog.open({
                            title: projectDefaultUiConfiguration
                                ? 'Use the project default sidebar?'
                                : 'Reset sidebar customization?',
                            description: projectDefaultUiConfiguration
                                ? 'This removes your personal customization, so your sidebar follows the default your project admins set.'
                                : 'This removes your personal customization and restores the default sidebar.',
                            primaryButton: {
                                children: 'Reset',
                                status: 'danger',
                                onClick: () => resetUiConfiguration(),
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }
                    data-attr="sidebar-customization-reset"
                >
                    {projectDefaultUiConfiguration ? 'Reset to project default' : 'Reset customization'}
                </LemonButton>
            </div>
        </div>
    )
}

export function SidebarLayoutSetting(): JSX.Element {
    const { isSidebarFlattened, sidebarDensity, userLoading } = useValues(uiCustomizationLogic)
    const { setSidebarFlattened, setSidebarDensity } = useActions(uiCustomizationLogic)

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <LemonSwitch
                className="py-2"
                checked={isSidebarFlattened}
                onChange={(checked) => setSidebarFlattened(checked)}
                loading={userLoading}
                label={
                    <span className="flex flex-col">
                        <span>Flatten sections</span>
                        <span className="text-xs font-normal text-secondary">
                            Show all sidebar items as one flat list, without section headers.
                        </span>
                    </span>
                }
                bordered
                fullWidth
                data-attr="sidebar-customization-flattened"
            />
            <div className="flex flex-col gap-2">
                <LemonLabel>Density</LemonLabel>
                <LemonSegmentedButton
                    value={sidebarDensity}
                    onChange={(value) => setSidebarDensity(value as SidebarDensity)}
                    options={[
                        { value: 'comfortable', label: 'Comfortable' },
                        { value: 'compact', label: 'Compact' },
                    ]}
                    size="small"
                    data-attr="sidebar-customization-density"
                />
            </div>
        </div>
    )
}

export function SidebarAccentColorSetting(): JSX.Element {
    const { projectAccentColor } = useValues(uiCustomizationLogic)
    const { setProjectAccentColor } = useActions(uiCustomizationLogic)

    return (
        <div className="flex items-center gap-2 max-w-160">
            <LemonColorPicker
                colors={ACCENT_COLOR_SWATCHES}
                selectedColor={projectAccentColor}
                onSelectColor={(color) => setProjectAccentColor(color)}
                onClearColor={() => setProjectAccentColor(null)}
                showCustomColor
            />
            {projectAccentColor && (
                <LemonButton
                    size="small"
                    onClick={() => setProjectAccentColor(null)}
                    data-attr="sidebar-customization-accent-clear"
                >
                    Clear
                </LemonButton>
            )}
        </div>
    )
}

export function SidebarItemsSetting(): JSX.Element {
    const { isSidebarSectionShown, isSidebarItemShown, sidebarItemOrder, userLoading } = useValues(uiCustomizationLogic)
    const { setSidebarSectionShown, setSidebarItemShown, setSidebarItemOrder } = useActions(uiCustomizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const isFlagShown = (item: SidebarCustomizableItem): boolean =>
        !item.flag || !!(featureFlags as Record<string, boolean | string>)[item.flag]

    const renderItemSwitch = (item: SidebarCustomizableItem): JSX.Element => {
        const { key } = item
        if (!key) {
            return (
                <LemonSwitch
                    key={item.label}
                    className="py-2"
                    checked={true}
                    disabledReason={`${item.label} always stays visible`}
                    label={<ItemLabel icon={item.icon} label={item.label} description={item.description} />}
                    bordered
                    fullWidth
                    data-attr={`sidebar-customization-item-${item.label.toLowerCase()}`}
                />
            )
        }
        return (
            <LemonSwitch
                key={key}
                className="py-2"
                checked={isSidebarItemShown(key)}
                onChange={(checked) => setSidebarItemShown(key, checked)}
                loading={userLoading}
                label={<ItemLabel icon={item.icon} label={item.label} description={item.description} />}
                bordered
                fullWidth
                data-attr={`sidebar-customization-item-${key}`}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4 max-w-160">
            {SIDEBAR_CUSTOMIZABLE_SECTIONS.map((section) => {
                const items = section.items.filter(isFlagShown)
                // A section with no items of its own is a single sidebar element, so it toggles
                // directly rather than heading a group.
                if (items.length === 0) {
                    return (
                        <LemonSwitch
                            key={section.key}
                            className="py-2"
                            checked={isSidebarSectionShown(section.key)}
                            onChange={(checked) => setSidebarSectionShown(section.key, checked)}
                            loading={userLoading}
                            label={
                                <ItemLabel
                                    icon={section.icon}
                                    label={section.label}
                                    description={section.description}
                                />
                            }
                            bordered
                            fullWidth
                            data-attr={`sidebar-customization-section-${section.key}`}
                        />
                    )
                }

                // The Project section's items are reorderable: render them in their effective
                // order with move buttons, so the settings list mirrors the sidebar.
                const itemsByOrderKey = new Map(
                    items.filter((item) => item.orderKey).map((item) => [item.orderKey as string, item])
                )
                const fullOrder = orderKeys(DEFAULT_SIDEBAR_ITEM_ORDER, sidebarItemOrder)
                const renderedOrderKeys = fullOrder.filter((orderKey) => itemsByOrderKey.has(orderKey))
                const orderedItems: SidebarCustomizableItem[] = [
                    ...renderedOrderKeys
                        .map((orderKey) => itemsByOrderKey.get(orderKey))
                        .filter((item): item is SidebarCustomizableItem => !!item),
                    ...items.filter((item) => !item.orderKey),
                ]

                return (
                    <div key={section.key} className="flex flex-col gap-2">
                        <LemonLabel>{section.label}</LemonLabel>
                        {orderedItems.map((item) => {
                            if (!item.orderKey) {
                                return renderItemSwitch(item)
                            }
                            const index = renderedOrderKeys.indexOf(item.orderKey)
                            return (
                                <div key={item.orderKey} className="flex items-center gap-1">
                                    <div className="flex-1">{renderItemSwitch(item)}</div>
                                    <MoveButtons
                                        canMoveUp={index > 0}
                                        canMoveDown={index < renderedOrderKeys.length - 1}
                                        onMove={(direction) => {
                                            const next = withKeyMovedAmong(
                                                fullOrder,
                                                renderedOrderKeys,
                                                item.orderKey as string,
                                                direction
                                            )
                                            if (next) {
                                                setSidebarItemOrder(next)
                                            }
                                        }}
                                        dataAttrPrefix={`sidebar-customization-item-${item.orderKey}`}
                                    />
                                </div>
                            )
                        })}
                    </div>
                )
            })}
            <div className="flex flex-col gap-2">
                <LemonLabel>Bottom of the sidebar</LemonLabel>
                {SIDEBAR_CUSTOMIZABLE_FOOTER_ITEMS.filter(isFlagShown).map((item) => renderItemSwitch(item))}
            </div>
        </div>
    )
}

export function SidebarMyToolsSetting(): JSX.Element {
    const { enabledToolPaths, customProductsLoading } = useValues(customProductsLogic)
    const { setToolEnabled } = useActions(customProductsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidebarToolOrder } = useValues(uiCustomizationLogic)
    const { setSidebarToolOrder } = useActions(uiCustomizationLogic)

    const products = getDefaultTreeProducts()
        .filter((product) => !product.flag || (featureFlags as Record<string, boolean | string>)[product.flag])
        .filter((product) => !getProductAccessDisabledReason(product))
    const productsByCategory = new Map<string, FileSystemImport[]>()
    for (const product of products) {
        const category = product.category || 'Other'
        if (!productsByCategory.has(category)) {
            productsByCategory.set(category, [])
        }
        productsByCategory.get(category)?.push(product)
    }
    // Mirror the sidebar tree ordering: hardcoded category order, then visualOrder, then name.
    const sortProducts = (a: FileSystemImport, b: FileSystemImport): number => {
        if (a.visualOrder !== undefined && b.visualOrder !== undefined) {
            return a.visualOrder - b.visualOrder
        }
        if (a.visualOrder !== undefined) {
            return -1
        }
        if (b.visualOrder !== undefined) {
            return 1
        }
        return (a.displayLabel ?? a.path).localeCompare(b.displayLabel ?? b.path, undefined, {
            sensitivity: 'accent',
        })
    }

    // The nav also shows companion tools alongside the ones the user picked, so the order list
    // must include them too or reordering would silently push them to the end.
    const shownToolPaths = new Set(enabledToolPaths)
    for (const path of enabledToolPaths) {
        for (const companion of PRODUCTS_SHOWN_WITH_SELECTED_PRODUCTS[path] ?? []) {
            shownToolPaths.add(companion)
        }
    }
    const enabledProductsInDefaultOrder = [...productsByCategory.entries()]
        .sort(
            (a, b) =>
                getCategoryOrder(a[0]) - getCategoryOrder(b[0]) ||
                a[0].localeCompare(b[0], undefined, { sensitivity: 'accent' })
        )
        .flatMap(([, categoryProducts]) => [...categoryProducts].sort(sortProducts))
        .filter((product) => shownToolPaths.has(product.path))
    const orderedEnabledPaths = orderKeys(
        enabledProductsInDefaultOrder.map((product) => product.path),
        sidebarToolOrder
    )
    const productByPath = new Map(products.map((product) => [product.path, product]))

    return (
        // The colorful-product-icons group class turns on each tool's brand color, as in the navbar.
        <div className="flex flex-col gap-4 max-w-160 group/colorful-product-icons colorful-product-icons-true">
            {orderedEnabledPaths.length > 1 && (
                <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                        <LemonLabel>Order</LemonLabel>
                        {!!sidebarToolOrder?.length && (
                            <LemonButton
                                size="xsmall"
                                onClick={() => setSidebarToolOrder([])}
                                data-attr="sidebar-customization-tool-order-reset"
                            >
                                Reset order
                            </LemonButton>
                        )}
                    </div>
                    {orderedEnabledPaths.map((path, index) => {
                        const product = productByPath.get(path)
                        if (!product) {
                            return null
                        }
                        return (
                            <div
                                key={path}
                                className="flex items-center justify-between gap-2 border rounded px-3 py-1"
                            >
                                <ItemLabel
                                    icon={iconForType(product.iconType, product.iconColor)}
                                    label={product.displayLabel ?? product.path}
                                />
                                <MoveButtons
                                    canMoveUp={index > 0}
                                    canMoveDown={index < orderedEnabledPaths.length - 1}
                                    onMove={(direction) => {
                                        const next = withKeyMovedAmong(
                                            orderedEnabledPaths,
                                            orderedEnabledPaths,
                                            path,
                                            direction
                                        )
                                        if (next) {
                                            setSidebarToolOrder(next)
                                        }
                                    }}
                                    dataAttrPrefix={`sidebar-customization-tool-order-${path}`}
                                />
                            </div>
                        )
                    })}
                </div>
            )}
            {[...productsByCategory.entries()]
                .sort(
                    (a, b) =>
                        getCategoryOrder(a[0]) - getCategoryOrder(b[0]) ||
                        a[0].localeCompare(b[0], undefined, { sensitivity: 'accent' })
                )
                .map(([category, categoryProducts]) => (
                    <div key={category} className="flex flex-col gap-2">
                        <LemonLabel>{category}</LemonLabel>
                        {[...categoryProducts].sort(sortProducts).map((product) => {
                            const description: string | undefined = product.sceneKey
                                ? productConfiguration[product.sceneKey]?.description
                                : undefined
                            const docsHref: string | undefined = product.intents?.length
                                ? PRODUCT_BRANDING[product.intents[0]]?.docsHref
                                : undefined
                            return (
                                <LemonSwitch
                                    key={product.path}
                                    className="py-2"
                                    checked={enabledToolPaths.has(product.path)}
                                    onChange={(checked) => setToolEnabled(product.path, checked)}
                                    loading={customProductsLoading}
                                    label={
                                        <ItemLabel
                                            icon={iconForType(product.iconType, product.iconColor)}
                                            label={product.displayLabel ?? product.path}
                                            description={description}
                                            docsHref={docsHref}
                                        />
                                    }
                                    bordered
                                    fullWidth
                                    data-attr={`sidebar-customization-tool-${product.path}`}
                                />
                            )
                        })}
                    </div>
                ))}
        </div>
    )
}
