import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconX } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { addProductIntent } from 'lib/utils/product-intents'

import { pinnedFolderLogic } from '~/layout/panel-layout/PinnedFolder/pinnedFolderLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { getTreeItemsProducts } from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { navPanelSalesLedLogic } from './navPanelSalesLedLogic'

export function NavPanelAdvertisement(): JSX.Element | null {
    const logic = navPanelSalesLedLogic()
    const { oldestSalesLedProduct } = useValues(logic)
    const { pinnedFolder } = useValues(pinnedFolderLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    // Only show when custom-products:// sidebar is active and not collapsed
    if (pinnedFolder !== 'custom-products://' || isLayoutNavCollapsed) {
        return null
    }

    if (!oldestSalesLedProduct) {
        return null
    }

    return <NavPanelAdvertisementContent salesLedProduct={oldestSalesLedProduct} />
}

export function NavPanelAdvertisementContent({
    salesLedProduct,
}: {
    salesLedProduct: { product_path: string; reason_text: string | null; id: string }
}): JSX.Element | null {
    const allProducts = getTreeItemsProducts()
    const productInfo: FileSystemImport | undefined = allProducts.find(
        (p: FileSystemImport) => p.path === salesLedProduct.product_path
    )

    const logic = navPanelAdvertisementLogic({ productKey: salesLedProduct.product_path })
    const { hideAdvertisement } = useActions(logic)
    const { hidden } = useValues(logic)

    useEffect(() => {
        if (!hidden && productInfo) {
            posthog.capture('nav panel advertisement shown', {
                product_path: salesLedProduct.product_path,
                product_id: salesLedProduct.id,
            })
        }
    }, [salesLedProduct.product_path, salesLedProduct.id, productInfo, hidden])

    if (hidden || !productInfo) {
        return null
    }

    const reasonText =
        salesLedProduct.reason_text ??
        "We've added this product to your sidebar because we believe you'd benefit from it! Your TAM will reach out to help you learn more about it."

    return (
        <div className="w-full">
            <Link
                to={productInfo.href}
                className="text-primary"
                onClick={() => {
                    posthog.capture('nav panel advertisement clicked', {
                        product_path: salesLedProduct.product_path,
                        product_id: salesLedProduct.id,
                    })
                    if (productInfo.intents && productInfo.intents.length > 0) {
                        const productKey = productInfo.intents[0]
                        if (productKey in ProductKey) {
                            addProductIntent({
                                product_type: productKey as ProductKey,
                                intent_context: ProductIntentContext.NAV_PANEL_ADVERTISEMENT_CLICKED,
                                metadata: { product_path: salesLedProduct.product_path },
                            })
                        }
                    }
                }}
            >
                <div className="border rounded-sm bg-primary text-xs *:flex *:gap-2 *:px-2 *:py-1">
                    <div className="flex justify-between mt-1">
                        <div className="flex items-center gap-2">
                            <strong>
                                <span role="img" aria-label="sparkles">
                                    ✨
                                </span>{' '}
                                {productInfo.path}
                            </strong>
                        </div>
                        <LemonButton
                            icon={<IconX className="text-muted m-1" />}
                            tooltip="Dismiss"
                            tooltipPlacement="right"
                            size="xxsmall"
                            onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()

                                posthog.capture('nav panel advertisement dismissed', {
                                    product_path: salesLedProduct.product_path,
                                    product_id: salesLedProduct.id,
                                })

                                hideAdvertisement()
                            }}
                            noPadding
                        />
                    </div>

                    <div className="flex flex-col gap-1">
                        <p className="mb-0">{reasonText}</p>
                    </div>
                </div>
            </Link>
        </div>
    )
}
