import { useActions, useValues } from 'kea'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { editCustomProductsModalLogic } from './editCustomProductsModalLogic'

export function EditCustomProductsModal(): JSX.Element {
    const {
        isOpen,
        customProductsLoading,
        selectedPaths,
        allowSidebarSuggestions,
        saving,
        categories,
        productsByCategory,
    } = useValues(editCustomProductsModalLogic)
    const { toggleProduct, setAllowSidebarSuggestions, save, closeModal } = useActions(editCustomProductsModalLogic)

    const handleSave = (): void => {
        save()
        closeModal()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Edit my sidebar apps"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={saving ? 'Saving...' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSave} loading={saving || customProductsLoading}>
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
                        {categories.map((category: string) => {
                            const products = productsByCategory.get(category) || []

                            return (
                                <div key={category}>
                                    <h3 className="text-xs font-semibold text-tertiary mb-2 pl-6">{category}</h3>
                                    <div className="space-y-1">
                                        {products.map((product: FileSystemImport) => {
                                            const icon = iconForType(
                                                (product.iconType ?? undefined) as any,
                                                product.iconColor
                                            )
                                            return (
                                                <LemonCheckbox
                                                    key={product.path}
                                                    checked={selectedPaths.has(product.path)}
                                                    onChange={() => toggleProduct(product.path)}
                                                    label={
                                                        <span className="flex items-center gap-2">
                                                            {icon}
                                                            <span>{product.path}</span>
                                                            {product.tags?.length && (
                                                                <>
                                                                    {product.tags.map((tag: string) => (
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
