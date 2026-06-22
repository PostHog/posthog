import { useRef } from 'react'

import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetTileFilterReadOnlyValue, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import {
    EXPERIMENTS_WIDGET_STATUS_OPTIONS,
    type ExperimentsListWidgetStatus,
    parseExperimentsListWidgetConfig,
    patchExperimentsListWidgetConfig,
} from './experimentsWidgetConfigValidation'

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
