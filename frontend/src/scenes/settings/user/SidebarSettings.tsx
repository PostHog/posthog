import { useActions, useValues } from 'kea'

import { LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { getDefaultTreeProducts, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import {
    SIDEBAR_CUSTOMIZABLE_FOOTER_ITEMS,
    SIDEBAR_CUSTOMIZABLE_SECTIONS,
    SidebarCustomizableItem,
} from '~/layout/panel-layout/sidebarCustomization'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { FileSystemImport } from '~/queries/schema/schema-general'

function ItemLabel({ icon, label }: { icon: JSX.Element; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-2">
            <span className="text-lg text-secondary flex items-center">{icon}</span>
            {label}
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
                    label={<ItemLabel icon={item.icon} label={item.label} />}
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
                label={<ItemLabel icon={item.icon} label={item.label} />}
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
                            label={<ItemLabel icon={section.icon} label={section.label} />}
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
        <div className="flex flex-col gap-4 max-w-160">
            {[...productsByCategory.entries()]
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([category, categoryProducts]) => (
                    <div key={category} className="flex flex-col gap-2">
                        <LemonLabel>{category}</LemonLabel>
                        {categoryProducts.map((product) => (
                            <LemonSwitch
                                key={product.path}
                                checked={enabledToolPaths.has(product.path)}
                                onChange={(checked) => setToolEnabled(product.path, checked)}
                                loading={customProductsLoading}
                                label={
                                    <ItemLabel
                                        icon={iconForType(product.iconType, product.iconColor)}
                                        label={product.displayLabel ?? product.path}
                                    />
                                }
                                bordered
                                fullWidth
                                data-attr={`sidebar-customization-tool-${product.path}`}
                            />
                        ))}
                    </div>
                ))}
        </div>
    )
}
