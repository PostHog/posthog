import { useActions, useValues } from 'kea'

import { IconEye, IconHide, IconSearch, IconTrends } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { CREATED_BY_ME, analyticsListLogic } from './analyticsListLogic'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPES, AnalyticsTypeFilter } from './analyticsUtils'

const ANYONE = 'anyone'

/** Search, type, creator and the personal toggle, all one height so the row reads as one bar. */
export function AnalyticsListFilters(): JSX.Element {
    const { filters, filtersActive, searchInput, scope, showPersonal, mode } = useValues(analyticsListLogic)
    const { setSearchInput, setFilters, clearFilters, setShowPersonal } = useActions(analyticsListLogic)
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)

    const memberNames = new Map<string, string>([
        [ANYONE, 'Created by anyone'],
        [CREATED_BY_ME, 'Created by me'],
        ...meFirstMembers
            .filter((member) => member.user.uuid !== user?.uuid)
            .map((member): [string, string] => [member.user.uuid, fullName(member.user) || member.user.email]),
    ])

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup className="h-8 w-56 max-w-full">
                <InputGroupAddon align="inline-start">
                    <InputGroupText>
                        <IconSearch />
                    </InputGroupText>
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    aria-label="Search analytics"
                    placeholder="Search"
                    value={searchInput}
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) => setSearchInput(event.target.value)}
                    data-attr="analytics-list-search"
                />
            </InputGroup>
            <ToggleGroup
                size="lg"
                variant="default"
                aria-label="Filter by type"
                className="h-8"
                value={[filters.type]}
                onValueChange={(value: string[]) => value[0] && setFilters({ type: value[0] as AnalyticsTypeFilter })}
            >
                <ToggleGroupItem value="all" size="lg" data-attr="analytics-list-type-filter">
                    <IconTrends />
                    All
                </ToggleGroupItem>
                {ANALYTICS_TYPES.map((info) => (
                    <ToggleGroupItem
                        key={info.type}
                        value={info.type}
                        size="lg"
                        aria-label={info.pluralLabel}
                        title={info.pluralLabel}
                        data-attr="analytics-list-type-filter"
                    >
                        <span
                            className="flex items-center [&_svg]:size-4"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ color: info.color }}
                        >
                            <AnalyticsTypeIcon type={info.type} />
                        </span>
                        <span className="hidden @6xl/analytics:inline">{info.pluralLabel}</span>
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            {scope === 'all' && (
                <Select
                    value={filters.createdBy ?? ANYONE}
                    onValueChange={(value: string | null) =>
                        setFilters({ createdBy: !value || value === ANYONE ? null : value })
                    }
                    onOpenChange={(open: boolean) => open && ensureAllMembersLoaded()}
                >
                    <SelectTrigger
                        size="sm"
                        aria-label="Filter by creator"
                        className="h-8 w-44"
                        data-attr="analytics-list-created-by"
                    >
                        <SelectValue>{(value: string) => memberNames.get(value) ?? 'Created by anyone'}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        {[...memberNames.entries()].map(([value, label]) => (
                            <SelectItem key={value} value={value}>
                                {label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            )}
            {scope === 'all' && mode === 'feed' && (
                <Button
                    variant="outline"
                    size="sm"
                    className="h-8"
                    onClick={() => setShowPersonal(!showPersonal)}
                    data-attr="analytics-list-toggle-personal"
                >
                    {showPersonal ? <IconHide /> : <IconEye />}
                    {showPersonal ? 'Hide personal' : 'Show personal'}
                </Button>
            )}
            {filtersActive && (
                <Button variant="link-muted" size="sm" onClick={() => clearFilters()} data-attr="analytics-list-clear">
                    Clear filters
                </Button>
            )}
        </div>
    )
}
