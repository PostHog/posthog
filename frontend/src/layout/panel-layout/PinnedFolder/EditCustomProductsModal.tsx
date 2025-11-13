import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import api from 'lib/api'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { getDefaultTreeProducts, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemImport } from '~/queries/schema/schema-general'

export interface EditCustomProductsModalProps {
    isOpen: boolean
    onClose: () => void
}

export function EditCustomProductsModal({ isOpen, onClose }: EditCustomProductsModalProps): JSX.Element {
    const { customProducts, customProductsLoading } = useValues(customProductsLogic)
    const { loadCustomProducts } = useActions(customProductsLogic)
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const allProducts = getDefaultTreeProducts().sort((a, b) => a.path.localeCompare(b.path || 'b'))

    // Filter products by feature flags (same logic as sidebar)
    const filteredProducts = allProducts.filter((f) => !f.flag || (featureFlags as Record<string, boolean>)[f.flag])
    const productsByCategory = new Map<string, FileSystemImport[]>()

    for (const product of filteredProducts) {
        const category = product.category || 'Other'
        if (!productsByCategory.has(category)) {
            productsByCategory.set(category, [])
        }
        productsByCategory.get(category)!.push(product)
    }

    const [selectedPaths, setSelectedPaths] = useState<Set<string>>(() => new Set())
    const [allowSidebarSuggestions, setAllowSidebarSuggestions] = useState(user?.allow_sidebar_suggestions ?? false)
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        if (isOpen) {
            loadCustomProducts()
        }
    }, [isOpen, loadCustomProducts])

    useEffect(() => {
        if (customProducts.length > 0) {
            setSelectedPaths(new Set(customProducts.map((item) => item.product_path)))
        }
    }, [customProducts])

    useEffect(() => {
        if (user) {
            setAllowSidebarSuggestions(user.allow_sidebar_suggestions ?? false)
        }
    }, [user])

    const handleToggleProduct = (productPath: string): void => {
        const newSelected = new Set(selectedPaths)
        if (newSelected.has(productPath)) {
            newSelected.delete(productPath)
        } else {
            newSelected.add(productPath)
        }
        setSelectedPaths(newSelected)
    }

    const handleSave = async (): Promise<void> => {
        setSaving(true)
        try {
            const products = Array.from(selectedPaths).map((path) => ({
                product_path: path,
            }))

            await api.userProductList.bulkUpdate({ products })

            if (user && user.allow_sidebar_suggestions !== allowSidebarSuggestions) {
                updateUser({ allow_sidebar_suggestions: allowSidebarSuggestions })
            }

            loadCustomProducts()
            onClose()
        } catch (error) {
            console.error('Failed to save custom products:', error)
        } finally {
            setSaving(false)
        }
    }

    const categories = Array.from(productsByCategory.keys()).sort()

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Edit my sidebar apps"
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose} disabled={saving}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSave} loading={saving}>
                        Save
                    </LemonButton>
                </>
            }
            width={600}
        >
            <div className="space-y-4">
                <div>
                    <p className="text-sm text-muted">
                        Select which products you want to see in your sidebar. You can change this anytime.
                    </p>
                </div>

                {customProductsLoading ? (
                    <div className="flex items-center justify-center py-8">
                        <Spinner />
                    </div>
                ) : (
                    <ScrollableShadows direction="vertical" className="max-h-[300px]" innerClassName="space-y-4 px-2">
                        {categories.map((category) => {
                            const products = productsByCategory.get(category) || []

                            return (
                                <div key={category}>
                                    <h3 className="text-xs font-semibold text-tertiary mb-2 pl-6">{category}</h3>
                                    <div className="space-y-1">
                                        {products.map((product) => {
                                            const icon = iconForType(product.iconType, product.iconColor)
                                            return (
                                                <LemonCheckbox
                                                    key={product.path}
                                                    checked={selectedPaths.has(product.path)}
                                                    onChange={() => handleToggleProduct(product.path)}
                                                    label={
                                                        <span className="flex items-center gap-2">
                                                            {icon}
                                                            <span>{product.path}</span>
                                                            {product.tags?.length && (
                                                                <>
                                                                    {product.tags.map((tag) => (
                                                                        <LemonTag
                                                                            key={tag}
                                                                            type={
                                                                                tag === 'alpha'
                                                                                    ? 'completion'
                                                                                    : tag === 'beta'
                                                                                      ? 'warning'
                                                                                      : 'success'
                                                                            }
                                                                            size="small"
                                                                            className="relative top-[1px]"
                                                                        >
                                                                            {tag.toUpperCase()}
                                                                        </LemonTag>
                                                                    ))}
                                                                </>
                                                            )}
                                                        </span>
                                                    }
                                                />
                                            )
                                        })}
                                    </div>
                                </div>
                            )
                        })}
                    </ScrollableShadows>
                )}

                <div className="flex flex-col items-start gap-2 border-t pt-4">
                    <LemonCheckbox
                        checked={allowSidebarSuggestions}
                        onChange={setAllowSidebarSuggestions}
                        label="Automatically suggest new products"
                    />
                    <span className="text-sm text-muted">
                        When we detect you are using a new product, we'll automatically add it to your sidebar as a
                        suggestion. We might also suggest products that are related to the ones you are using when we
                        launch a new product.
                        <br />
                        You can always remove these suggestions later.
                    </span>
                </div>
            </div>
        </LemonModal>
    )
}
