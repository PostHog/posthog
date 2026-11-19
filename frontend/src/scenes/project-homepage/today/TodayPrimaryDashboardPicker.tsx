import { useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { IconSearch } from '@posthog/icons'
import {
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    InputGroupAddon,
} from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { dashboardsModel } from '~/models/dashboardsModel'

import { TodayPrimaryDashboardPickerSource, todayPrimaryDashboardLogic } from './todayPrimaryDashboardLogic'

const NO_DASHBOARD = 'none'

export function TodayPrimaryDashboardPicker({
    trigger,
    source,
}: {
    trigger: JSX.Element
    source: TodayPrimaryDashboardPickerSource
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { primaryDashboardPickerOpened, setPrimaryDashboard } = useActions(todayPrimaryDashboardLogic)
    const { nameSortedDashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [search, setSearch] = useState('')
    const primaryId = currentTeam?.primary_dashboard ?? null

    const nameById = useMemo(
        () => new Map(nameSortedDashboards.filter((d) => !d.deleted).map((d) => [String(d.id), d.name || 'Untitled'])),
        [nameSortedDashboards]
    )
    const query = search.trim().toLowerCase()
    const items = [
        ...(primaryId && !query ? [NO_DASHBOARD] : []),
        ...[...nameById].filter(([, name]) => name.toLowerCase().includes(query)).map(([id]) => id),
    ]

    return (
        <Combobox
            items={items}
            filter={null}
            value={primaryId ? String(primaryId) : null}
            inputValue={search}
            highlightItemOnHover
            itemToStringLabel={(id: string) => (id === NO_DASHBOARD ? '' : (nameById.get(id) ?? ''))}
            onInputValueChange={setSearch}
            onOpenChange={(open: boolean) => {
                if (open) {
                    loadDashboardsIfNeeded()
                    primaryDashboardPickerOpened(source)
                } else {
                    setSearch('')
                }
            }}
            onValueChange={(id: string | null) =>
                setPrimaryDashboard(!id || id === NO_DASHBOARD ? null : Number(id), source)
            }
        >
            <ComboboxTrigger ref={triggerRef} render={trigger} />
            <ComboboxContent
                anchor={triggerRef}
                align={source === 'empty' ? 'center' : 'end'}
                className="w-72 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput
                    placeholder="Search dashboards"
                    aria-label="Search dashboards"
                    data-attr="today-home-primary-dashboard-search"
                    autoFocus
                    showTrigger={false}
                    className="h-7"
                >
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxList>
                    {(id: string) =>
                        id === NO_DASHBOARD ? (
                            <ComboboxItem
                                key={id}
                                value={id}
                                className="text-muted-foreground"
                                data-attr="today-home-primary-dashboard-clear"
                            >
                                <span className="min-w-0 truncate">Don't show a dashboard</span>
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={id} value={id} data-attr="today-home-primary-dashboard-pick">
                                <span className="min-w-0 truncate">{nameById.get(id)}</span>
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>
                <ComboboxEmpty>{dashboardsLoading ? 'Loading dashboards…' : 'No dashboards match'}</ComboboxEmpty>
            </ComboboxContent>
        </Combobox>
    )
}
