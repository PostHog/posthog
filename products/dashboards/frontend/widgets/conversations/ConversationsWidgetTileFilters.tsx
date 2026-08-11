import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetTileFilterReadOnlyValue, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import {
    CONVERSATIONS_TICKET_STATUS_OPTIONS,
    type ConversationsTicketStatus,
    parseConversationsWidgetConfig,
    patchConversationsWidgetStatus,
} from './conversationsWidgetConfigValidation'

export function ConversationsWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: DashboardWidgetTileFiltersProps): JSX.Element {
    const status = parseConversationsWidgetConfig(config).status ?? 'all'
    const { getLatestConfig, persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig, config)
    const statusLabel = CONVERSATIONS_TICKET_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status

    if (!onUpdateConfig) {
        return (
            <WidgetTileFiltersBar dataAttr="conversations-widget-filters-readonly">
                <WidgetTileFilterReadOnlyValue>
                    <span className="text-secondary">Status:</span> {statusLabel}
                </WidgetTileFilterReadOnlyValue>
            </WidgetTileFiltersBar>
        )
    }
    return (
        <WidgetTileFiltersBar dataAttr="conversations-widget-filters">
            <LemonSelect
                size="small"
                value={status}
                disabled={!!disabledReason}
                disabledReason={disabledReason ?? undefined}
                options={CONVERSATIONS_TICKET_STATUS_OPTIONS}
                onChange={(value) => {
                    if (value) {
                        const nextConfig = patchConversationsWidgetStatus(
                            getLatestConfig(),
                            value as ConversationsTicketStatus
                        )
                        void persistConfigNow(nextConfig)
                    }
                }}
            />
        </WidgetTileFiltersBar>
    )
}
