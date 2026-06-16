import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { fullName } from 'lib/utils'
import { membersLogic } from 'scenes/organization/membersLogic'

import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetTileFilterReadOnlyValue, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import {
    EXPERIMENTS_WIDGET_STATUS_OPTIONS,
    type ExperimentsListWidgetStatus,
    parseExperimentsListWidgetConfig,
    patchExperimentsListWidgetConfig,
} from './experimentsListWidgetConfigValidation'

function ExperimentsCreatorReadOnlyValue({ createdBy }: { createdBy: number }): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    useEffect(() => {
        ensureAllMembersLoaded()
    }, [ensureAllMembersLoaded])
    const creator = meFirstMembers.find((member) => member.user.id === createdBy)?.user
    return (
        <WidgetTileFilterReadOnlyValue>
            <span className="text-secondary">Creator:</span> {creator ? fullName(creator) : `User ${createdBy}`}
        </WidgetTileFilterReadOnlyValue>
    )
}

export function ExperimentsListWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: DashboardWidgetTileFiltersProps): JSX.Element {
    const parsed = parseExperimentsListWidgetConfig(config)
    const status = parsed.status ?? 'all'
    const createdBy = parsed.createdBy ?? null

    const configRef = useRef(config)
    configRef.current = config
    const { persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig)

    const canUpdate = !!onUpdateConfig && !disabledReason

    const applyStatus = async (value: ExperimentsListWidgetStatus): Promise<void> => {
        const nextConfig = patchExperimentsListWidgetConfig(configRef.current, { status: value })
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    const applyCreatedBy = async (userId: number | null): Promise<void> => {
        const nextConfig = patchExperimentsListWidgetConfig(configRef.current, { createdBy: userId })
        configRef.current = nextConfig
        await persistConfigNow(nextConfig)
    }

    if (!onUpdateConfig) {
        const statusLabel = EXPERIMENTS_WIDGET_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
        return (
            <WidgetTileFiltersBar dataAttr="experiments-list-widget-tile-filters-readonly">
                <WidgetTileFilterReadOnlyValue>
                    <span className="text-secondary">Status:</span> {statusLabel}
                </WidgetTileFilterReadOnlyValue>
                {createdBy != null ? <ExperimentsCreatorReadOnlyValue createdBy={createdBy} /> : null}
            </WidgetTileFiltersBar>
        )
    }

    return (
        <WidgetTileFiltersBar dataAttr="experiments-list-widget-tile-filters">
            <LemonSelect
                size="small"
                value={status}
                disabled={!canUpdate}
                disabledReason={disabledReason ?? undefined}
                options={EXPERIMENTS_WIDGET_STATUS_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        void applyStatus(value)
                    }
                }}
            />
            <MemberSelect
                type="secondary"
                size="small"
                value={createdBy}
                onChange={(user) => {
                    void applyCreatedBy(user?.id ?? null)
                }}
            />
        </WidgetTileFiltersBar>
    )
}
