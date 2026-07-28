import { useActions, useValues } from 'kea'

import { LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PRODUCT_BRANDING } from 'scenes/welcome/productBranding'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { getDefaultTreeProducts, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import {
    SIDEBAR_CUSTOMIZABLE_FOOTER_ITEMS,
    SIDEBAR_CUSTOMIZABLE_SECTIONS,
    SidebarCustomizableItem,
} from '~/layout/panel-layout/sidebarCustomization'
import { HomepageConfiguration } from '~/layout/scenes/ConfigureHomeModal'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { productConfiguration } from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'

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

export function SidebarItemsSetting(): JSX.Element {
    const { isSidebarSectionShown, isSidebarItemShown, userLoading } = useValues(uiCustomizationLogic)
    const { setSidebarSectionShown, setSidebarItemShown } = useActions(uiCustomizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const renderItemSwitch = (item: SidebarCustomizableItem, sectionHiddenReason?: string | false): JSX.Element => {
        const { key } = item
        if (!key) {
            // Locked items stay visible even when their section is hidden, so no section reason here.
            return (
                <LemonSwitch
                    key={item.label}
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
                checked={isSidebarItemShown(key)}
                onChange={(checked) => setSidebarItemShown(key, checked)}
                loading={userLoading}
                disabledReason={sectionHiddenReason || undefined}
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
                const sectionShown = isSidebarSectionShown(section.key)
                const items = section.items.filter(
                    (item) => !item.flag || (featureFlags as Record<string, boolean | string>)[item.flag]
                )
                return (
                    <div key={section.key} className="flex flex-col gap-2">
                        <LemonSwitch
                            checked={sectionShown}
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
                        {items.length > 0 && (
                            <div className="flex flex-col gap-2 pl-8">
                                {items.map((item) =>
                                    renderItemSwitch(
                                        item,
                                        !sectionShown && `Hidden because the ${section.label} section is hidden`
                                    )
                                )}
                            </div>
                        )}
                    </div>
                )
            })}
            <div className="flex flex-col gap-2">
                <LemonLabel>Bottom of the sidebar</LemonLabel>
                {SIDEBAR_CUSTOMIZABLE_FOOTER_ITEMS.filter(
                    (item) => !item.flag || (featureFlags as Record<string, boolean | string>)[item.flag]
                ).map((item) => renderItemSwitch(item))}
            </div>
        </div>
    )
}

export function SidebarMyToolsSetting(): JSX.Element {
    const { enabledToolPaths, customProductsLoading } = useValues(customProductsLogic)
    const { setToolEnabled } = useActions(customProductsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const products = getDefaultTreeProducts().filter(
        (product) => !product.flag || (featureFlags as Record<string, boolean | string>)[product.flag]
    )
    const productsByCategory = new Map<string, FileSystemImport[]>()
    for (const product of products) {
        const category = product.category || 'Other'
        if (!productsByCategory.has(category)) {
            productsByCategory.set(category, [])
        }
        productsByCategory.get(category)?.push(product)
    }

    return (
        // The colorful-product-icons group class turns on each tool's brand color, as in the navbar.
        <div className="flex flex-col gap-4 max-w-160 group/colorful-product-icons colorful-product-icons-true">
            {[...productsByCategory.entries()]
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([category, categoryProducts]) => (
                    <div key={category} className="flex flex-col gap-2">
                        <LemonLabel>{category}</LemonLabel>
                        {categoryProducts.map((product) => {
                            const description: string | undefined = product.sceneKey
                                ? productConfiguration[product.sceneKey]?.description
                                : undefined
                            const docsHref: string | undefined = product.intents?.length
                                ? PRODUCT_BRANDING[product.intents[0]]?.docsHref
                                : undefined
                            return (
                                <LemonSwitch
                                    key={product.path}
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
