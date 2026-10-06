import { useActions, useValues } from 'kea'

import { IconFolder, IconSearch } from '@posthog/icons'
import {
    Button,
    Chip,
    ChipClose,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
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

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { tagsModel } from '~/models/tagsModel'

import { CREATED_BY_ME, analyticsListLogic } from './analyticsListLogic'
import { ANALYTICS_TYPES, AnalyticsTypeFilter } from './analyticsUtils'

const TYPE_OPTIONS: { value: AnalyticsTypeFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    ...ANALYTICS_TYPES.map((info) => ({ value: info.type, label: info.pluralLabel })),
]

export function AnalyticsListFilters(): JSX.Element {
    const { filters, filtersActive, searchInput, folderBreadcrumbs } = useValues(analyticsListLogic)
    const { setSearchInput, setFilters, clearFilters } = useActions(analyticsListLogic)
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)
    const { tags: allTags, tagsLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)

    const memberNames = new Map<string, string>([
        [CREATED_BY_ME, 'Me'],
        ...meFirstMembers
            .filter((member) => member.user.uuid !== user?.uuid)
            .map((member): [string, string] => [member.user.uuid, fullName(member.user) || member.user.email]),
    ])
    const memberOptions = [...memberNames.keys()]

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup className="w-72 max-w-full">
                <InputGroupAddon align="inline-start">
                    <InputGroupText>
                        <IconSearch />
                    </InputGroupText>
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    aria-label="Search analytics"
                    placeholder="Search analytics"
                    value={searchInput}
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) => setSearchInput(event.target.value)}
                    data-attr="analytics-list-search"
                />
            </InputGroup>
            <ToggleGroup
                size="sm"
                aria-label="Filter by type"
                className="hidden @2xl/analytics:flex"
                value={[filters.type]}
                onValueChange={(value: string[]) => value[0] && setFilters({ type: value[0] as AnalyticsTypeFilter })}
            >
                {TYPE_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value} data-attr="analytics-list-type-filter">
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <Select
                value={filters.type}
                onValueChange={(value: AnalyticsTypeFilter | null) => value && setFilters({ type: value })}
            >
                <SelectTrigger
                    size="sm"
                    aria-label="Filter by type"
                    className="@2xl/analytics:hidden"
                    data-attr="analytics-list-type-select"
                >
                    <SelectValue>
                        {(value: AnalyticsTypeFilter) =>
                            value === 'all' ? 'All types' : TYPE_OPTIONS.find((option) => option.value === value)?.label
                        }
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {TYPE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.value === 'all' ? 'All types' : option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <Combobox
                items={memberOptions}
                value={filters.createdBy}
                onValueChange={(value: string | null) => setFilters({ createdBy: value })}
                onOpenChange={(open: boolean) => open && ensureAllMembersLoaded()}
                itemToStringLabel={(value: string) => memberNames.get(value) ?? ''}
            >
                <ComboboxInput
                    placeholder="Created by anyone"
                    aria-label="Filter by creator"
                    className="w-44"
                    data-attr="analytics-list-created-by"
                />
                <ComboboxContent>
                    <ComboboxEmpty>No one matches that name.</ComboboxEmpty>
                    <ComboboxList>
                        {(value: string) => (
                            <ComboboxItem key={value} value={value}>
                                {memberNames.get(value)}
                            </ComboboxItem>
                        )}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
            <TagsCombobox
                value={filters.tags}
                onChange={(tags) => setFilters({ tags })}
                onOpen={loadTagsIfNeeded}
                loading={tagsLoading}
                options={allTags}
                allowCustomValues={false}
                placeholder="Tags"
                className="min-w-36"
                dataAttr="analytics-list-tags"
            />
            {filters.folder !== null && (
                <Chip size="sm">
                    <IconFolder />
                    {filters.folder === '' ? 'Project root' : folderBreadcrumbs[folderBreadcrumbs.length - 1]?.name}
                    <ChipClose
                        aria-label="Leave folder"
                        onClick={() => setFilters({ folder: null })}
                        data-attr="analytics-list-folder-clear"
                    />
                </Chip>
            )}
            {filtersActive && (
                <Button variant="link-muted" size="sm" onClick={() => clearFilters()} data-attr="analytics-list-clear">
                    Clear filters
                </Button>
            )}
        </div>
    )
}
