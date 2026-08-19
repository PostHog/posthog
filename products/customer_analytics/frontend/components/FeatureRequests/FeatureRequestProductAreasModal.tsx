import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import type { FeatureRequestProductAreaApi } from '../../generated/api.schemas'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestProductAreasModal(): JSX.Element {
    const {
        productAreasOpen,
        filteredProductAreas,
        productAreasLoading,
        productAreasError,
        editingProductAreaId,
        productAreaFormOpen,
        productAreaName,
        productAreaDisplayOrder,
        productAreaActive,
        savingProductArea,
        productAreaSaveDisabledReason,
        productAreaSearch,
    } = useValues(featureRequestsLogic)
    const {
        closeProductAreas,
        closeProductAreaForm,
        startNewProductArea,
        startEditingProductArea,
        setProductAreaName,
        setProductAreaSearch,
        setProductAreaDisplayOrder,
        setProductAreaActive,
        saveProductArea,
        loadProductAreas,
    } = useActions(featureRequestsLogic)

    const columns: LemonTableColumns<FeatureRequestProductAreaApi> = [
        { title: 'Name', key: 'name', dataIndex: 'name' },
        {
            title: 'Status',
            key: 'is_active',
            render: (_, area) => (
                <LemonTag type={area.is_active ? 'success' : 'default'}>
                    {area.is_active ? 'Active' : 'Inactive'}
                </LemonTag>
            ),
        },
        { title: 'Order', key: 'display_order', render: (_, area) => area.display_order ?? 0 },
        {
            title: '',
            key: 'actions',
            align: 'right',
            render: (_, area) => (
                <LemonButton type="tertiary" size="small" onClick={() => startEditingProductArea(area)}>
                    Edit
                </LemonButton>
            ),
        },
    ]

    return (
        <LemonModal
            isOpen={productAreasOpen}
            onClose={closeProductAreas}
            title="Manage product areas"
            width={720}
            className="[&_.LemonModal__content]:min-h-0 [&_.LemonModal__content]:flex-1 [&_.LemonModal__content]:overflow-hidden"
            footer={
                <LemonButton type="secondary" onClick={closeProductAreas}>
                    Done
                </LemonButton>
            }
        >
            <div className="flex h-full min-h-0 flex-col gap-4">
                {productAreasError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadProductAreas }}>
                        {productAreasError}
                    </LemonBanner>
                )}
                <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
                    <LemonInput
                        type="search"
                        value={productAreaSearch}
                        onChange={setProductAreaSearch}
                        placeholder="Search product areas"
                        className="min-w-48 flex-1"
                        data-attr="product-areas-search"
                    />
                    <LemonButton type="primary" onClick={startNewProductArea} data-attr="add-product-area-button">
                        Add product area
                    </LemonButton>
                </div>
                {productAreaFormOpen && (
                    <div className="flex shrink-0 flex-col gap-3 rounded border p-4">
                        <h3 className="m-0">{editingProductAreaId ? 'Edit product area' : 'New product area'}</h3>
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Name</LemonLabel>
                            <LemonInput
                                value={productAreaName}
                                onChange={setProductAreaName}
                                placeholder="Product analytics"
                                maxLength={200}
                                fullWidth
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Display order</LemonLabel>
                            <LemonInput
                                type="number"
                                min={0}
                                value={productAreaDisplayOrder}
                                onChange={(value) => setProductAreaDisplayOrder(Math.max(0, value ?? 0))}
                                fullWidth
                            />
                        </div>
                        <LemonSwitch
                            checked={productAreaActive}
                            onChange={setProductAreaActive}
                            label="Available for new requests"
                        />
                        <div className="flex justify-end gap-2">
                            <LemonButton type="secondary" onClick={closeProductAreaForm}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={saveProductArea}
                                loading={savingProductArea}
                                disabledReason={productAreaSaveDisabledReason}
                            >
                                {editingProductAreaId ? 'Save changes' : 'Save'}
                            </LemonButton>
                        </div>
                    </div>
                )}
                <div className="min-h-0 flex-1 overflow-hidden">
                    <LemonTable
                        dataSource={filteredProductAreas}
                        columns={columns}
                        rowKey="id"
                        loading={productAreasLoading}
                        emptyState={
                            productAreaSearch.trim()
                                ? 'No product areas match this search. Try another search.'
                                : 'No product areas yet'
                        }
                        allowContentScroll
                    />
                </div>
            </div>
        </LemonModal>
    )
}
