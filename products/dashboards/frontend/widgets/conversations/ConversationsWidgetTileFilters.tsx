import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { teamLogic } from 'scenes/teamLogic'

import { AssigneeMultiSelect, type AssigneeFilterEntry } from 'products/conversations/frontend/components/Assignee'
import { clearFilterButtonProps } from 'products/conversations/frontend/components/clearFilterButtonProps'
import { priorityMultiselectOptions, statusOptions } from 'products/conversations/frontend/types'

import type { DashboardWidgetTileFiltersProps } from '../registry'
import { useWidgetTileConfigPersist } from '../widgetTileFiltersHooks'
import { WidgetTileFilterReadOnlyLabel, WidgetTileFiltersBar } from '../widgetTileFiltersReadOnly'
import {
    type ConversationsTicketAssignee,
    parseConversationsWidgetConfig,
    patchConversationsWidgetFilterFields,
    type ConversationsTicketPriority,
} from './conversationsWidgetConfigValidation'
import { conversationsWidgetSavedViewsLogic } from './conversationsWidgetSavedViewsLogic'

const NO_SAVED_VIEW = '__none__'

function priorityFilterLabel(priorities: ConversationsTicketPriority[]): string {
    if (priorities.length === 0) {
        return 'Priority'
    }
    if (priorities.length === 1) {
        return priorityMultiselectOptions.find((option) => option.key === priorities[0])?.label ?? priorities[0]
    }
    return `${priorities.length} priorities`
}

function ConversationsPriorityFilter({
    value,
    onChange,
}: {
    value: ConversationsTicketPriority[]
    onChange: (value: ConversationsTicketPriority[]) => void
}): JSX.Element {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="space-y-px p-1">
                    {priorityMultiselectOptions.map((option) => (
                        <LemonButton
                            key={option.key}
                            type="tertiary"
                            size="small"
                            fullWidth
                            icon={
                                <LemonCheckbox checked={value.includes(option.key)} className="pointer-events-none" />
                            }
                            onClick={() => {
                                const nextValue = value.includes(option.key)
                                    ? value.filter((priority) => priority !== option.key)
                                    : [...value, option.key]
                                onChange(nextValue)
                            }}
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                {...clearFilterButtonProps(value.length > 0 ? () => onChange([]) : null, 'Clear priority filter')}
            >
                {priorityFilterLabel(value)}
            </LemonButton>
        </LemonDropdown>
    )
}

export function ConversationsWidgetTileFilters({
    config,
    onUpdateConfig,
    disabledReason,
}: DashboardWidgetTileFiltersProps): JSX.Element {
    const parsedConfig = parseConversationsWidgetConfig(config)
    const status = parsedConfig.status ?? 'all'
    const priorities = parsedConfig.priorities ?? []
    const assignees = (parsedConfig.assignees ?? []) as AssigneeFilterEntry[]
    const savedViewId = parsedConfig.savedViewId ?? null
    const { currentProjectId } = useValues(teamLogic)
    const savedViewsLogic = conversationsWidgetSavedViewsLogic({ projectId: currentProjectId })
    const { savedViewOptions, savedViewsLoaded, savedViewsLoading, savedViewsError, savedViewLabelById } =
        useValues(savedViewsLogic)
    const { loadSavedViews } = useActions(savedViewsLogic)
    const { getLatestConfig, persistConfigNow } = useWidgetTileConfigPersist(onUpdateConfig, config)
    const statusLabel = statusOptions.find((option) => option.value === status)?.label ?? status
    const prioritiesLabel = priorities.length === 0 ? 'All priorities' : `${priorities.length} selected`
    const assigneesLabel = assignees.length === 0 ? 'All assignees' : `${assignees.length} selected`
    const savedViewLabel = savedViewId ? (savedViewLabelById[savedViewId] ?? savedViewId) : null

    if (!onUpdateConfig || disabledReason) {
        return (
            <WidgetTileFiltersBar dataAttr="conversations-widget-filters-readonly">
                {savedViewLabel ? (
                    <WidgetTileFilterReadOnlyLabel name="Saved view" value={savedViewLabel} />
                ) : (
                    <>
                        <WidgetTileFilterReadOnlyLabel name="Status" value={statusLabel} />
                        <WidgetTileFilterReadOnlyLabel name="Priority" value={prioritiesLabel} />
                        <WidgetTileFilterReadOnlyLabel name="Assignee" value={assigneesLabel} />
                    </>
                )}
            </WidgetTileFiltersBar>
        )
    }
    return (
        <WidgetTileFiltersBar dataAttr="conversations-widget-filters">
            <div className="flex w-full min-w-0 flex-nowrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={savedViewId ?? NO_SAVED_VIEW}
                    loading={savedViewsLoading}
                    disabled={!!savedViewsError}
                    disabledReason={savedViewsError ? 'Could not load saved views.' : undefined}
                    options={[{ value: NO_SAVED_VIEW, label: 'No saved view' }, ...savedViewOptions]}
                    menu={{
                        onVisibilityChange: (visible) => {
                            if (visible && !savedViewsLoaded && !savedViewsLoading) {
                                loadSavedViews()
                            }
                        },
                    }}
                    renderButtonContent={(option) =>
                        option?.value === NO_SAVED_VIEW ? (
                            'Saved view'
                        ) : (
                            <span className="block max-w-32 truncate">{option?.label ?? 'Saved view'}</span>
                        )
                    }
                    onChange={(value) => {
                        const nextConfig = patchConversationsWidgetFilterFields(getLatestConfig(), {
                            savedViewId: value === NO_SAVED_VIEW ? null : value,
                        })
                        void persistConfigNow(nextConfig)
                    }}
                />
                {savedViewsError ? (
                    <LemonButton size="small" loading={savedViewsLoading} onClick={loadSavedViews}>
                        Retry
                    </LemonButton>
                ) : null}
                {!savedViewId ? (
                    <>
                        <LemonSelect
                            size="small"
                            value={status}
                            options={statusOptions}
                            renderButtonContent={(option) =>
                                option?.value === 'all' ? 'Status' : (option?.label ?? 'Status')
                            }
                            onChange={(value) => {
                                if (value) {
                                    const nextConfig = patchConversationsWidgetFilterFields(getLatestConfig(), {
                                        status: value,
                                    })
                                    void persistConfigNow(nextConfig)
                                }
                            }}
                        />
                        <ConversationsPriorityFilter
                            value={priorities}
                            onChange={(value) => {
                                const nextConfig = patchConversationsWidgetFilterFields(getLatestConfig(), {
                                    priorities: value,
                                })
                                void persistConfigNow(nextConfig)
                            }}
                        />
                        <AssigneeMultiSelect
                            value={assignees}
                            emptyLabel="Assignee"
                            onChange={(value) => {
                                const nextConfig = patchConversationsWidgetFilterFields(getLatestConfig(), {
                                    assignees: value as ConversationsTicketAssignee[],
                                })
                                void persistConfigNow(nextConfig)
                            }}
                        />
                    </>
                ) : null}
            </div>
        </WidgetTileFiltersBar>
    )
}
