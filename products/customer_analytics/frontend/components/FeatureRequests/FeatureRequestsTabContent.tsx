import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { FeatureRequestApi, FeatureRequestProductAreaApi } from '../../generated/api.schemas'
import { featureRequestsLogic } from './featureRequestsLogic'

function CreateRequestModal(): JSX.Element {
    const {
        createRequestOpen,
        title,
        description,
        accountId,
        productAreaIds,
        accountOptions,
        productAreaOptions,
        accountsLoading,
        accountsError,
        productAreasLoading,
        productAreasError,
        submittingRequest,
        submitDisabledReason,
    } = useValues(featureRequestsLogic)
    const {
        closeCreateRequest,
        setTitle,
        setDescription,
        setAccountId,
        setAccountSearch,
        setProductAreaIds,
        submitRequest,
        loadAccounts,
        loadProductAreas,
    } = useActions(featureRequestsLogic)

    return (
        <LemonModal
            isOpen={createRequestOpen}
            onClose={closeCreateRequest}
            title="New feature request"
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeCreateRequest}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitRequest}
                        loading={submittingRequest}
                        disabledReason={submitDisabledReason}
                        data-attr="save-feature-request"
                    >
                        Save request
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {accountsError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadAccounts('') }}>
                        {accountsError}
                    </LemonBanner>
                )}
                {productAreasError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadProductAreas }}>
                        {productAreasError}
                    </LemonBanner>
                )}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Title</LemonLabel>
                    <LemonInput
                        value={title}
                        onChange={setTitle}
                        placeholder="What does the customer need?"
                        maxLength={400}
                        autoFocus
                        fullWidth
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Description</LemonLabel>
                    <LemonTextArea
                        value={description}
                        onChange={setDescription}
                        placeholder="Describe the request in the customer's language"
                        minRows={5}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Account</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        value={accountId ? [accountId] : []}
                        onChange={(values) => setAccountId(values[0] ?? null)}
                        onInputChange={setAccountSearch}
                        options={accountOptions}
                        placeholder="Search for an account"
                        loading={accountsLoading}
                        fullWidth
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Product areas</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        value={productAreaIds}
                        onChange={setProductAreaIds}
                        options={productAreaOptions}
                        placeholder="Select one or more product areas"
                        loading={productAreasLoading}
                    />
                </div>
            </div>
        </LemonModal>
    )
}

function ProductAreasModal(): JSX.Element {
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

function FeatureRequestDetail({ request }: { request: FeatureRequestApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-4xl">
            <div>
                <LemonButton type="tertiary" size="small" to={urls.customerAnalyticsFeatureRequests()}>
                    Back to feature requests
                </LemonButton>
            </div>
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="m-0">{request.title}</h2>
                    <LemonTag type="primary">Requested</LemonTag>
                </div>
                <span className="text-secondary">
                    Last updated <TZLabel time={request.updated_at} />
                </span>
            </div>
            <div className="border rounded p-4">
                <LemonMarkdown>{request.description}</LemonMarkdown>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="border rounded p-4 flex flex-col gap-1">
                    <span className="font-semibold">Account</span>
                    <Link to={urls.customerAnalyticsAccount(request.account.id)}>{request.account.name}</Link>
                </div>
                <div className="border rounded p-4 flex flex-col gap-2">
                    <span className="font-semibold">Product areas</span>
                    <div className="flex flex-wrap gap-1">
                        {request.product_areas.map((area) => (
                            <LemonTag key={area.id}>{area.name}</LemonTag>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

export function FeatureRequestsTabContent(): JSX.Element {
    const {
        featureRequests,
        featureRequestsLoading,
        featureRequestsError,
        activeRequest,
        activeRequestLoading,
        activeRequestError,
        activeRequestId,
    } = useValues(featureRequestsLogic)
    const { openCreateRequest, openProductAreas, loadFeatureRequests, loadActiveRequest } =
        useActions(featureRequestsLogic)

    const editorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )
    const managerDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Manager
    )

    if (activeRequestId) {
        if (activeRequestError) {
            return (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadActiveRequest(activeRequestId) }}
                >
                    {activeRequestError}
                </LemonBanner>
            )
        }
        if (activeRequestLoading || !activeRequest) {
            return <div className="p-4 text-secondary">Loading feature request…</div>
        }
        return <FeatureRequestDetail request={activeRequest} />
    }

    const columns: LemonTableColumns<FeatureRequestApi> = [
        {
            title: 'Request',
            key: 'title',
            render: (_, request) => (
                <Link to={urls.customerAnalyticsFeatureRequests(request.id)} className="font-semibold">
                    {request.title}
                </Link>
            ),
        },
        {
            title: 'Account',
            key: 'account',
            render: (_, request) => request.account.name,
        },
        {
            title: 'Product areas',
            key: 'product_areas',
            render: (_, request) => (
                <div className="flex flex-wrap gap-1">
                    {request.product_areas.map((area) => (
                        <LemonTag key={area.id}>{area.name}</LemonTag>
                    ))}
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'request_status',
            render: () => <LemonTag type="primary">Requested</LemonTag>,
        },
        {
            title: 'Updated',
            key: 'updated_at',
            render: (_, request) => <TZLabel time={request.updated_at} />,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center justify-end gap-2">
                <LemonButton type="secondary" onClick={openProductAreas} disabledReason={managerDisabledReason}>
                    Manage product areas
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={openCreateRequest}
                    disabledReason={editorDisabledReason}
                    data-attr="new-feature-request"
                >
                    New request
                </LemonButton>
            </div>
            {featureRequestsError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadFeatureRequests }}>
                    {featureRequestsError}
                </LemonBanner>
            )}
            <LemonTable
                dataSource={featureRequests}
                columns={columns}
                rowKey="id"
                loading={featureRequestsLoading}
                emptyState="No feature requests yet"
            />
            <CreateRequestModal />
            <ProductAreasModal />
        </div>
    )
}
