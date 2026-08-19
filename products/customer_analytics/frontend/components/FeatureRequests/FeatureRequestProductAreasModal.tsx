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
        productAreas,
        productAreasLoading,
        productAreasError,
        editingProductAreaId,
        productAreaName,
        productAreaDisplayOrder,
        productAreaActive,
        savingProductArea,
        productAreaSaveDisabledReason,
    } = useValues(featureRequestsLogic)
    const {
        closeProductAreas,
        startNewProductArea,
        startEditingProductArea,
        setProductAreaName,
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
            footer={
                <LemonButton type="secondary" onClick={closeProductAreas}>
                    Done
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-4">
                {productAreasError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadProductAreas }}>
                        {productAreasError}
                    </LemonBanner>
                )}
                <LemonTable
                    dataSource={productAreas}
                    columns={columns}
                    rowKey="id"
                    loading={productAreasLoading}
                    emptyState="No product areas yet"
                />
                <div className="border rounded p-4 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                        <h3 className="m-0">{editingProductAreaId ? 'Edit product area' : 'New product area'}</h3>
                        {editingProductAreaId && (
                            <LemonButton type="tertiary" size="small" onClick={startNewProductArea}>
                                Add another
                            </LemonButton>
                        )}
                    </div>
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
                    <div>
                        <LemonButton
                            type="primary"
                            onClick={saveProductArea}
                            loading={savingProductArea}
                            disabledReason={productAreaSaveDisabledReason}
                        >
                            {editingProductAreaId ? 'Save changes' : 'Add product area'}
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
