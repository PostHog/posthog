import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconArrowLeft, IconBuilding, IconDocument, IconFolder, IconPeople } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonSkeleton,
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
import { FEATURE_REQUESTS_PAGE_SIZE, featureRequestsLogic } from './featureRequestsLogic'

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

function FeatureRequestDetailSkeleton(): JSX.Element {
    return (
        <div
            className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm"
            role="status"
            aria-label="Loading feature request"
        >
            <div className="flex flex-col gap-3.5 mb-6 pb-5 border-b border-primary" aria-hidden>
                <LemonSkeleton className="h-7 w-32 rounded" />
                <div className="flex flex-col gap-2 min-w-0">
                    <LemonSkeleton className="h-6 w-2/3 max-w-xl rounded" />
                    <div className="flex items-center gap-2">
                        <LemonSkeleton className="h-5 w-20 rounded-full" />
                        <LemonSkeleton className="h-3 w-56 rounded" />
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 @5xl:grid-cols-[minmax(0,80ch)_minmax(22rem,1fr)] gap-5" aria-hidden>
                <div className="min-w-0 flex flex-col gap-3">
                    <div className="flex items-center gap-3">
                        <LemonSkeleton className="h-4 w-28 rounded" />
                        <div className="h-px min-w-4 flex-1 bg-border-light" />
                    </div>
                    <div className="flex flex-col gap-2.5">
                        <LemonSkeleton className="h-3 w-full rounded" />
                        <LemonSkeleton className="h-3 w-11/12 rounded" />
                        <LemonSkeleton className="h-3 w-4/5 rounded" />
                        <LemonSkeleton className="h-3 w-2/3 rounded" />
                    </div>
                </div>

                <div className="flex flex-col min-w-0 gap-5">
                    <div className="flex flex-col gap-3">
                        <div className="flex items-center gap-3">
                            <LemonSkeleton className="h-4 w-24 rounded" />
                            <div className="h-px min-w-4 flex-1 bg-border-light" />
                        </div>
                        <div className="flex items-center gap-3 rounded border border-primary bg-surface-primary px-3 py-2.5">
                            <LemonSkeleton className="size-8 shrink-0 rounded" />
                            <div className="flex flex-1 flex-col gap-1.5">
                                <LemonSkeleton className="h-3.5 w-32 rounded" />
                                <LemonSkeleton className="h-2.5 w-16 rounded" />
                            </div>
                        </div>
                    </div>
                    <div className="flex flex-col gap-3">
                        <div className="flex items-center gap-3">
                            <LemonSkeleton className="h-4 w-28 rounded" />
                            <div className="h-px min-w-4 flex-1 bg-border-light" />
                        </div>
                        <div className="flex gap-1.5">
                            <LemonSkeleton className="h-5 w-24 rounded-full" />
                            <LemonSkeleton className="h-5 w-20 rounded-full" />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

function FeatureRequestDetailSection({
    icon,
    title,
    children,
}: {
    icon: ReactNode
    title: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <div className="flex items-center gap-3 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="flex shrink-0 items-center text-secondary [&_svg]:size-[0.9375rem]">{icon}</span>
                    <h2 className="m-0 truncate text-sm font-semibold tracking-tight">{title}</h2>
                </div>
                <div className="h-px min-w-4 flex-1 bg-border-light" />
            </div>
            <div>{children}</div>
        </section>
    )
}

function FeatureRequestDetail({ request }: { request: FeatureRequestApi }): JSX.Element {
    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <header className="flex flex-col gap-3.5 mb-6 pb-5 border-b border-primary">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    to={urls.customerAnalyticsFeatureRequests()}
                    className="-ml-2 w-fit"
                >
                    Feature requests
                </LemonButton>
                <div className="flex flex-col gap-2 min-w-0">
                    <h1 className="m-0 break-words text-xl font-bold leading-tight tracking-tight">{request.title}</h1>
                    <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary">
                        <LemonTag type="primary">Requested</LemonTag>
                        <span className="flex items-center gap-2 flex-wrap">
                            <span className="flex items-center gap-1">
                                <span>Created</span>
                                <TZLabel time={request.created_at} />
                            </span>
                            <span aria-hidden>·</span>
                            <span className="flex items-center gap-1">
                                <span>Last updated</span>
                                <TZLabel time={request.updated_at} />
                            </span>
                        </span>
                    </div>
                </div>
            </header>

            <div className="grid grid-cols-1 @5xl:grid-cols-[minmax(0,80ch)_minmax(22rem,1fr)] gap-5">
                <div className="min-w-0">
                    <FeatureRequestDetailSection icon={<IconDocument />} title="Description">
                        <LemonMarkdown
                            disableImages
                            className="text-sm text-secondary leading-relaxed break-words [&>*+*]:mt-3"
                        >
                            {request.description}
                        </LemonMarkdown>
                    </FeatureRequestDetailSection>
                </div>

                <aside className="flex flex-col min-w-0 gap-5">
                    <FeatureRequestDetailSection icon={<IconPeople />} title="Requesters">
                        <Link
                            to={urls.customerAnalyticsAccount(request.account.id)}
                            className="flex items-center gap-3 rounded border border-primary bg-surface-primary px-3 py-2.5 text-default hover:text-primary"
                        >
                            <span className="flex size-8 shrink-0 items-center justify-center rounded bg-fill-highlight-50 text-secondary">
                                <IconBuilding className="size-4" />
                            </span>
                            <span className="flex flex-col min-w-0">
                                <span className="truncate font-medium">{request.account.name}</span>
                                <span className="text-xs text-tertiary">Account</span>
                            </span>
                        </Link>
                    </FeatureRequestDetailSection>

                    <FeatureRequestDetailSection icon={<IconFolder />} title="Product areas">
                        <div className="flex flex-wrap gap-1.5">
                            {request.product_areas.map((area) => (
                                <LemonTag key={area.id}>{area.name}</LemonTag>
                            ))}
                        </div>
                    </FeatureRequestDetailSection>
                </aside>
            </div>
        </div>
    )
}

export function FeatureRequestsTabContent(): JSX.Element {
    const {
        featureRequestsResponse,
        featureRequestsResponseLoading,
        featureRequestsError,
        featureRequestsPage,
        activeRequest,
        activeRequestLoading,
        activeRequestError,
        activeRequestId,
    } = useValues(featureRequestsLogic)
    const { openCreateRequest, openProductAreas, loadFeatureRequests, loadActiveRequest, setFeatureRequestsPage } =
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
            return <FeatureRequestDetailSkeleton />
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
                dataSource={featureRequestsResponse.results}
                columns={columns}
                rowKey="id"
                loading={featureRequestsResponseLoading}
                emptyState="No feature requests yet"
                nouns={['feature request', 'feature requests']}
                pagination={{
                    controlled: true,
                    currentPage: featureRequestsPage,
                    pageSize: FEATURE_REQUESTS_PAGE_SIZE,
                    entryCount: featureRequestsResponse.count,
                    onBackward:
                        featureRequestsPage > 1 ? () => setFeatureRequestsPage(featureRequestsPage - 1) : undefined,
                    onForward:
                        featureRequestsPage * FEATURE_REQUESTS_PAGE_SIZE < featureRequestsResponse.count
                            ? () => setFeatureRequestsPage(featureRequestsPage + 1)
                            : undefined,
                }}
            />
            <CreateRequestModal />
            <ProductAreasModal />
        </div>
    )
}
