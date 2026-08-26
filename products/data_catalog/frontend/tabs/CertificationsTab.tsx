import { useActions, useValues } from 'kea'

import { IconPlusSmall, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { CertificationStatusFilter, certificationsLogic } from '../certificationsLogic'
import { NewCertificationModal } from '../components/NewCertificationModal'
import type { DataCatalogCertificationApi } from '../generated/api.schemas'

const STATUS_FILTER_OPTIONS: { value: CertificationStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'proposed', label: 'Proposed' },
    { value: 'certified', label: 'Certified' },
    { value: 'deprecated', label: 'Deprecated' },
]

const STATUS_TAG: Record<string, { label: string; type: 'warning' | 'success' | 'muted' }> = {
    proposed: { label: 'Proposed', type: 'warning' },
    certified: { label: 'Certified', type: 'success' },
    deprecated: { label: 'Deprecated', type: 'muted' },
}

export function CertificationsTab(): JSX.Element {
    const { filteredCertifications, certificationsLoading, filters, actionsInFlight } = useValues(certificationsLogic)
    const {
        setFilters,
        loadCertifications,
        openNewCertificationModal,
        certifyCertification,
        deprecateCertification,
        revokeCertification,
    } = useActions(certificationsLogic)

    const confirmRevoke = (certification: DataCatalogCertificationApi): void => {
        LemonDialog.open({
            title: 'Revoke this certification?',
            content: (
                <div className="text-sm text-secondary">
                    Revoking deletes the trust mark on {certification.target_name}. This cannot be undone.
                </div>
            ),
            primaryButton: {
                children: 'Revoke',
                status: 'danger',
                onClick: () => revokeCertification(certification.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const columns: LemonTableColumns<DataCatalogCertificationApi> = [
        {
            title: 'Target',
            key: 'target_name',
            render: (_, certification) => certification.target_name,
        },
        {
            title: 'Type',
            key: 'target_type',
            render: (_, certification) => <LemonTag type="option">{certification.target_type}</LemonTag>,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, certification) => {
                const tag =
                    certification.status === 'proposed' && certification.proposed_status === 'deprecated'
                        ? { label: 'Deprecation proposed', type: 'warning' as const }
                        : (STATUS_TAG[certification.status] ?? { label: certification.status, type: 'muted' as const })
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'Notes',
            key: 'notes',
            render: (_, certification) => certification.notes || <span className="text-secondary">-</span>,
        },
        {
            title: 'Certified by',
            key: 'certified_by',
            render: (_, certification) =>
                certification.certified_by?.email || <span className="text-secondary">-</span>,
        },
        {
            key: 'actions',
            width: 0,
            render: (_, certification) => {
                const inFlight = !!actionsInFlight[certification.id]
                return (
                    <More
                        overlay={
                            <>
                                {certification.status !== 'certified' && (
                                    <LemonButton
                                        fullWidth
                                        loading={inFlight}
                                        onClick={() => certifyCertification(certification.id)}
                                    >
                                        Certify
                                    </LemonButton>
                                )}
                                {certification.status !== 'deprecated' && (
                                    <LemonButton
                                        fullWidth
                                        loading={inFlight}
                                        onClick={() => deprecateCertification(certification.id)}
                                    >
                                        Deprecate
                                    </LemonButton>
                                )}
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    disabledReason={inFlight ? 'Working' : undefined}
                                    onClick={() => confirmRevoke(certification)}
                                >
                                    Revoke
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex justify-between gap-2 flex-wrap items-center">
                <LemonInput
                    type="search"
                    placeholder="Search certifications"
                    value={filters.search}
                    onChange={(search) => setFilters({ search })}
                />
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonSegmentedButton
                        value={filters.status}
                        onChange={(status) => setFilters({ status })}
                        options={STATUS_FILTER_OPTIONS}
                        size="small"
                    />
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        size="small"
                        loading={certificationsLoading}
                        onClick={() => loadCertifications()}
                    >
                        Reload
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconPlusSmall />}
                        size="small"
                        onClick={openNewCertificationModal}
                        data-attr="data-catalog-new-certification-button"
                    >
                        Propose certification
                    </LemonButton>
                </div>
            </div>
            <LemonTable
                data-attr="data-catalog-certifications-table"
                dataSource={filteredCertifications}
                rowKey="id"
                columns={columns}
                loading={certificationsLoading}
                pagination={{ pageSize: 20 }}
                emptyState="No certifications match your filters."
                nouns={['certification', 'certifications']}
            />
            <NewCertificationModal />
        </div>
    )
}
