import { useActions, useValues } from 'kea'

import * as businessEvolutionPng from '@posthog/brand/hoggies/png/business-evolution'
import { IconEllipsis, IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type { AccountDocumentApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    documentStatusLabel,
    documentStatusTagType,
    documentTypeLabel,
    legalDocumentStatusLabel,
    legalDocumentStatusTagType,
    legalDocumentTypeLabel,
} from './accountDocumentLabels'
import { AccountDocumentModal } from './AccountDocumentModal'
import { AccountDocumentPreviewModal } from './AccountDocumentPreviewModal'
import { accountDocumentsLogic, AccountDocumentRow, NOT_LOADED } from './accountDocumentsLogic'

const HedgehogBusiness = pngHoggie(businessEvolutionPng)

// Matches the Relationships tab, the other client-side-paginated account tab.
const PAGE_SIZE = 10

function DocumentsEmptyState({
    title,
    detail,
    action,
    dataAttr,
}: {
    title: string
    detail: string
    action?: JSX.Element
    dataAttr: string
}): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center" data-attr={dataAttr}>
            <HedgehogBusiness className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
            {action}
        </div>
    )
}

function formatDate(value: string | null | undefined): string | null {
    if (!value) {
        return null
    }
    const parsed = dayjs(value)
    return parsed.isValid() ? parsed.format('MMM D, YYYY') : value
}

function DocumentDates({ document }: { document: AccountDocumentApi }): JSX.Element {
    const effective = formatDate(document.effective_date)
    const end = formatDate(document.end_date)
    if (!effective && !end) {
        return <span className="text-muted">—</span>
    }
    if (effective && end) {
        return (
            <span>
                {effective} to {end}
            </span>
        )
    }
    return <span>{effective ? `From ${effective}` : `Until ${end}`}</span>
}

export function AccountDocumentsExpansion({
    accountId,
    instanceId,
    embedded = true,
}: {
    accountId: string
    instanceId?: string
    embedded?: boolean
}): JSX.Element {
    const logic = accountDocumentsLogic({ accountId, instanceId })
    const {
        rows,
        documentsResult,
        documentsResultLoading,
        legalResultLoading,
        syncingDocumentId,
        deletingDocumentId,
        legalDownloadUrl,
    } = useValues(logic)
    const { openEditor, openPreview, syncDocument, deleteDocument, reportDocumentOpened, loadAll } = useActions(logic)

    const addButton = (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPlus />}
            onClick={() => openEditor()}
            data-attr="account-documents-add"
        >
            Add document
        </LemonButton>
    )

    const confirmDelete = (document: AccountDocumentApi): void => {
        LemonDialog.open({
            title: 'Remove this document?',
            description: `"${document.title}" is removed from this account. The document itself stays where it lives.`,
            primaryButton: { children: 'Remove', status: 'danger', onClick: () => deleteDocument(document) },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const columns: LemonTableColumns<AccountDocumentRow> = [
        {
            title: 'Document',
            key: 'title',
            render: (_, row) => {
                if (row.kind === 'legal') {
                    const { document } = row
                    return (
                        <div className="flex flex-col">
                            {document.download_available ? (
                                <Link
                                    to={legalDownloadUrl(document)}
                                    target="_blank"
                                    onClick={() => reportDocumentOpened(document, 'legal_download')}
                                >
                                    {legalDocumentTypeLabel(document.document_type)}
                                </Link>
                            ) : (
                                <span>{legalDocumentTypeLabel(document.document_type)}</span>
                            )}
                            <span className="text-xs text-secondary">Signed in PostHog by {document.company_name}</span>
                        </div>
                    )
                }
                const { document } = row
                return (
                    <div className="flex flex-col">
                        {document.source === 'pandadoc' ? (
                            <Link
                                to={document.pandadoc_url ?? undefined}
                                onClick={(event) => {
                                    // A plain click previews in place; cmd/ctrl-click still opens PandaDoc in a new tab.
                                    event.preventDefault()
                                    openPreview(document)
                                }}
                                data-attr="account-document-preview"
                            >
                                {document.title}
                            </Link>
                        ) : (
                            <Link
                                to={document.external_url}
                                target="_blank"
                                onClick={() => reportDocumentOpened(document, 'link')}
                            >
                                {document.title}
                            </Link>
                        )}
                        <span className="text-xs text-secondary">
                            {document.source === 'pandadoc' ? 'PandaDoc' : 'Link'}
                        </span>
                    </div>
                )
            },
        },
        {
            title: 'Type',
            key: 'type',
            render: (_, row) =>
                row.kind === 'legal' ? row.document.document_type : documentTypeLabel(row.document.document_type),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, row) =>
                row.kind === 'legal' ? (
                    <LemonTag type={legalDocumentStatusTagType(row.document.status)}>
                        {legalDocumentStatusLabel(row.document.status)}
                    </LemonTag>
                ) : (
                    <LemonTag type={documentStatusTagType(row.document.status)}>
                        {documentStatusLabel(row.document.status)}
                    </LemonTag>
                ),
        },
        {
            title: 'Dates',
            key: 'dates',
            render: (_, row) =>
                row.kind === 'account' ? (
                    <DocumentDates document={row.document} />
                ) : (
                    <span className="text-muted">—</span>
                ),
        },
        {
            title: 'Amount',
            key: 'amount',
            align: 'right',
            render: (_, row) =>
                row.kind === 'account' && row.document.amount != null ? (
                    humanFriendlyCurrency(Number(row.document.amount))
                ) : (
                    <span className="text-muted">—</span>
                ),
        },
        {
            title: 'Added',
            key: 'created_at',
            render: (_, row) => <TZLabel time={row.createdAt} />,
        },
        {
            key: 'actions',
            width: 0,
            render: (_, row) => {
                if (row.kind === 'legal') {
                    return null
                }
                const { document } = row
                const busy = syncingDocumentId === document.id || deletingDocumentId === document.id
                return (
                    <LemonMenu
                        items={[
                            document.source === 'pandadoc'
                                ? { label: 'Preview', onClick: () => openPreview(document) }
                                : null,
                            document.pandadoc_url
                                ? {
                                      label: 'Open in PandaDoc',
                                      to: document.pandadoc_url,
                                      targetBlank: true,
                                      onClick: () => reportDocumentOpened(document, 'pandadoc'),
                                  }
                                : null,
                            document.source === 'pandadoc'
                                ? { label: 'Refresh from PandaDoc', onClick: () => syncDocument(document) }
                                : null,
                            { label: 'Edit', onClick: () => openEditor(document) },
                            { label: 'Remove', status: 'danger', onClick: () => confirmDelete(document) },
                        ]}
                    >
                        <LemonButton
                            size="small"
                            icon={<IconEllipsis />}
                            loading={busy}
                            disabledReason={busy ? 'Working' : undefined}
                            data-attr="account-document-actions"
                        />
                    </LemonMenu>
                )
            },
        },
    ]

    if ((documentsResultLoading && documentsResult === NOT_LOADED) || (legalResultLoading && rows.length === 0)) {
        return (
            <div data-attr="account-documents-loading">
                <LemonSkeleton className="h-64 w-full" />
            </div>
        )
    }

    if (documentsResult.loadFailed) {
        return (
            <DocumentsEmptyState
                dataAttr="account-documents-error"
                title="Couldn't load documents"
                detail="Something went wrong loading this account's documents."
                action={
                    <LemonButton type="secondary" size="small" onClick={loadAll}>
                        Try again
                    </LemonButton>
                }
            />
        )
    }

    return (
        <div className="flex flex-col gap-2 @container">
            {rows.length === 0 ? (
                <DocumentsEmptyState
                    dataAttr="account-documents-empty"
                    title="No documents yet"
                    detail="Add quotes, order forms and contracts from PandaDoc or a link. Agreements the customer signs in PostHog show up here on their own."
                    action={addButton}
                />
            ) : (
                <>
                    <div className="flex flex-wrap justify-end gap-2">{addButton}</div>
                    <LemonTable<AccountDocumentRow>
                        size="small"
                        embedded={embedded}
                        dataSource={rows}
                        columns={columns}
                        rowKey="id"
                        pagination={{ pageSize: PAGE_SIZE, useUrl: false }}
                        data-attr="account-documents-table"
                    />
                </>
            )}
            <AccountDocumentModal accountId={accountId} instanceId={instanceId} />
            <AccountDocumentPreviewModal accountId={accountId} instanceId={instanceId} />
        </div>
    )
}
