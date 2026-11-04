import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { Avatar, AvatarFallback, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { fullNameOrEmail } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { MetricOwnerCombobox } from '../metrics/MetricOwnerCombobox'
import { QuillMetricStatusBadges } from './QuillMetricStatusBadges'
import { QuillMetricUnitEditor } from './QuillMetricUnitEditor'

export interface QuillMetricSummaryProps {
    metric: DataCatalogMetricApi
    saving: boolean
    onSaveUnit: (unit: string) => void
    onSaveOwner: (owner: string | null) => void
}

function SummaryItem({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-2 @2xl/main-content:flex-col @2xl/main-content:items-start @2xl/main-content:gap-0.5">
            <Text size="xs" variant="muted" render={<span />} className="w-24 shrink-0 @2xl/main-content:w-auto">
                {label}
            </Text>
            <div className="flex min-h-6 min-w-0 items-center gap-1.5 text-xs">{children}</div>
        </div>
    )
}

function Initial({ name }: { name: string }): JSX.Element {
    return (
        <Avatar size="xs">
            <AvatarFallback>{name.charAt(0).toUpperCase()}</AvatarFallback>
        </Avatar>
    )
}

export function QuillMetricSummary({ metric, saving, onSaveUnit, onSaveOwner }: QuillMetricSummaryProps): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    useOnMountEffect(() => {
        ensureAllMembersLoaded()
    })
    const ownerMember = metric.owner ? meFirstMembers.find((member) => member.user.email === metric.owner) : undefined
    const ownerName = ownerMember ? fullNameOrEmail(ownerMember.user) : metric.owner
    const approverName = metric.approved_by ? fullNameOrEmail(metric.approved_by) : null

    return (
        <div className="flex flex-col gap-2 @2xl/main-content:flex-row @2xl/main-content:flex-wrap @2xl/main-content:items-start @2xl/main-content:gap-x-8 @2xl/main-content:gap-y-2">
            <SummaryItem label="Status">
                <QuillMetricStatusBadges metric={metric} />
            </SummaryItem>
            <SummaryItem label="Owner">
                {ownerName && <Initial name={ownerName} />}
                <MetricOwnerCombobox
                    label={ownerName || 'Unassigned'}
                    variant="default"
                    loading={saving}
                    onChange={onSaveOwner}
                    dataAttr="data-catalog-metric-owner-select"
                />
            </SummaryItem>
            {approverName && (
                <SummaryItem label="Approved by">
                    <Initial name={approverName} />
                    <span className="truncate">{approverName}</span>
                    {metric.approved_at && (
                        <Text size="xs" variant="muted" render={<span />} className="shrink-0">
                            <TZLabel time={metric.approved_at} />
                        </Text>
                    )}
                </SummaryItem>
            )}
            <SummaryItem label="Last run">
                {metric.last_run_at ? <TZLabel time={metric.last_run_at} /> : <span>Never</span>}
            </SummaryItem>
            <SummaryItem label="Unit">
                <QuillMetricUnitEditor
                    key={metric.unit || ''}
                    unit={metric.unit || ''}
                    saving={saving}
                    onSave={onSaveUnit}
                />
            </SummaryItem>
        </div>
    )
}
