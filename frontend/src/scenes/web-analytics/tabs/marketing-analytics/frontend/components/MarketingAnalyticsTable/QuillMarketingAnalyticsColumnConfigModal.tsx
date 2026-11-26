import { useId } from 'react'

import { IconEye, IconHide, IconPin, IconPinFilled } from '@posthog/icons'
import {
    Button,
    Checkbox,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Field,
    FieldLabel,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemGroup,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

type SortDirection = 'ASC' | 'DESC'

const NO_VALUE = '__none__'
const DIRECTION_PLACEHOLDER = 'Select direction...'

export function QuillMarketingAnalyticsColumnConfigModal({
    isOpen,
    onClose,
    sortedColumns,
    hiddenColumns,
    pinnedColumns,
    hasSorting,
    currentSortColumn,
    currentSortDirection,
    sortOptions,
    directionOptions,
    resetDisabledReason,
    applyDisabledReason,
    onSortColumnChange,
    onSortDirectionChange,
    onSortToggle,
    onToggleVisibility,
    onTogglePinning,
    onReset,
    onApply,
}: {
    isOpen: boolean
    onClose: () => void
    sortedColumns: string[]
    hiddenColumns: string[]
    pinnedColumns: string[]
    hasSorting: boolean
    currentSortColumn: string | undefined
    currentSortDirection: SortDirection | undefined
    sortOptions: { label: string; value: string | null }[]
    directionOptions: { label: string; value: SortDirection | null; icon?: JSX.Element }[]
    resetDisabledReason: string | undefined
    applyDisabledReason: string | undefined
    onSortColumnChange: (column: string | null) => void
    onSortDirectionChange: (direction: SortDirection | null) => void
    onSortToggle: (column: string, direction: SortDirection) => void
    onToggleVisibility: (column: string) => void
    onTogglePinning: (column: string) => void
    onReset: () => void
    onApply: () => void
}): JSX.Element {
    const sortColumnId = useId()
    const sortDirectionId = useId()

    return (
        <Credenza open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Configure columns</CredenzaTitle>
                </CredenzaHeader>
                <CredenzaBody>
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-col gap-1">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <Heading size="sm" render={<h5 className="m-0" />}>
                                    Active filters
                                </Heading>
                                <Button variant="outline" onClick={onReset} disabledReason={resetDisabledReason}>
                                    Reset to defaults
                                </Button>
                            </div>
                            {hasSorting ? (
                                <Text size="xs" variant="muted" render={<div className="flex items-center gap-1" />}>
                                    <IconArrowUp />
                                    <span>
                                        Sorted by:{' '}
                                        <span className="font-medium text-foreground">{currentSortColumn}</span> (
                                        {currentSortDirection})
                                    </span>
                                </Text>
                            ) : (
                                <Text size="xs" variant="muted" render={<div className="italic" />}>
                                    No sorting applied
                                </Text>
                            )}
                            {hiddenColumns.length > 0 ? (
                                <Text size="xs" variant="muted" render={<div className="flex items-center gap-1" />}>
                                    <IconHide />
                                    <span>
                                        Hidden: <span className="font-medium">{hiddenColumns.join(', ')}</span>
                                    </span>
                                </Text>
                            ) : (
                                <Text size="xs" variant="muted" render={<div className="italic" />}>
                                    No hidden columns
                                </Text>
                            )}
                            {pinnedColumns.length > 0 ? (
                                <Text size="xs" variant="muted" render={<div className="flex items-center gap-1" />}>
                                    <IconPinFilled />
                                    <span>
                                        Pinned:{' '}
                                        <span className="font-medium text-foreground">{pinnedColumns.join(', ')}</span>
                                    </span>
                                </Text>
                            ) : (
                                <Text size="xs" variant="muted" render={<div className="italic" />}>
                                    No pinned columns
                                </Text>
                            )}
                        </div>

                        <div className="flex flex-col gap-2">
                            <Heading size="sm" render={<h4 className="m-0" />}>
                                Sorting
                            </Heading>
                            <Field orientation="horizontal">
                                <FieldLabel htmlFor={sortColumnId} className="min-w-20">
                                    Sort by:
                                </FieldLabel>
                                <Select<string>
                                    value={currentSortColumn ?? null}
                                    onValueChange={(next) =>
                                        onSortColumnChange(next === null || next === NO_VALUE ? null : next)
                                    }
                                >
                                    <SelectTrigger id={sortColumnId} className="min-w-0 flex-1">
                                        <SelectValue placeholder="Select column..." />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {sortOptions.map((option) => (
                                            <SelectItem key={option.value ?? NO_VALUE} value={option.value ?? NO_VALUE}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </Field>
                            <Field orientation="horizontal">
                                <FieldLabel htmlFor={sortDirectionId} className="min-w-20">
                                    Direction:
                                </FieldLabel>
                                <Select<string>
                                    value={currentSortDirection ?? null}
                                    onValueChange={(next) =>
                                        onSortDirectionChange(
                                            next === null || next === NO_VALUE ? null : (next as SortDirection)
                                        )
                                    }
                                >
                                    <SelectTrigger
                                        id={sortDirectionId}
                                        className="min-w-0 flex-1"
                                        disabledReason={
                                            !currentSortColumn ? 'Select a column to sort by first' : undefined
                                        }
                                    >
                                        <SelectValue placeholder={DIRECTION_PLACEHOLDER}>
                                            {(selected: string | null) =>
                                                selected === null
                                                    ? DIRECTION_PLACEHOLDER
                                                    : (directionOptions.find((option) => option.value === selected)
                                                          ?.label ?? DIRECTION_PLACEHOLDER)
                                            }
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {directionOptions.map((option) => (
                                            <SelectItem key={option.value ?? NO_VALUE} value={option.value ?? NO_VALUE}>
                                                {option.icon}
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </Field>
                        </div>

                        <div className="flex flex-col gap-2">
                            <Heading size="sm" render={<h4 className="m-0" />}>
                                Column visibility and pinning
                            </Heading>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Hide columns you don't need or pin important ones to keep them always visible.
                            </Text>
                            <ItemGroup combined>
                                {sortedColumns.map((columnName) => {
                                    const isHidden = hiddenColumns.includes(columnName)
                                    const isPinned = pinnedColumns.includes(columnName)
                                    const isSortedAscending =
                                        currentSortColumn === columnName && currentSortDirection === 'ASC'
                                    const isSortedDescending =
                                        currentSortColumn === columnName && currentSortDirection !== 'ASC'
                                    const sortAscendingLabel = isSortedAscending ? 'Remove sort' : 'Sort ascending'
                                    const sortDescendingLabel = isSortedDescending ? 'Remove sort' : 'Sort descending'
                                    const pinLabel = isPinned ? 'Unpin column' : 'Pin column'
                                    const visibilityLabel = isHidden ? 'Show column' : 'Hide column'

                                    return (
                                        <Item key={columnName} variant="outline" size="xs" className="flex-wrap">
                                            <ItemContent className="min-w-0">
                                                <Checkbox
                                                    checked={!isHidden}
                                                    onCheckedChange={() => onToggleVisibility(columnName)}
                                                >
                                                    <span className="truncate">{columnName}</span>
                                                </Checkbox>
                                            </ItemContent>
                                            <ItemActions className="gap-1">
                                                <Button
                                                    size="icon"
                                                    variant={isSortedAscending ? 'primary' : 'outline'}
                                                    aria-label={sortAscendingLabel}
                                                    aria-pressed={isSortedAscending}
                                                    tooltip={sortAscendingLabel}
                                                    onClick={() => onSortToggle(columnName, 'ASC')}
                                                >
                                                    <IconArrowUp />
                                                </Button>
                                                <Button
                                                    size="icon"
                                                    variant={isSortedDescending ? 'primary' : 'outline'}
                                                    aria-label={sortDescendingLabel}
                                                    aria-pressed={isSortedDescending}
                                                    tooltip={sortDescendingLabel}
                                                    onClick={() => onSortToggle(columnName, 'DESC')}
                                                >
                                                    <IconArrowDown />
                                                </Button>
                                                <Button
                                                    size="icon"
                                                    variant={isPinned ? 'primary' : 'outline'}
                                                    aria-label={pinLabel}
                                                    aria-pressed={isPinned}
                                                    tooltip={pinLabel}
                                                    onClick={() => onTogglePinning(columnName)}
                                                >
                                                    {isPinned ? <IconPinFilled /> : <IconPin />}
                                                </Button>
                                                <Button
                                                    size="icon"
                                                    variant={isHidden ? 'primary' : 'outline'}
                                                    aria-label={visibilityLabel}
                                                    aria-pressed={isHidden}
                                                    tooltip={visibilityLabel}
                                                    onClick={() => onToggleVisibility(columnName)}
                                                >
                                                    {isHidden ? <IconHide /> : <IconEye />}
                                                </Button>
                                            </ItemActions>
                                        </Item>
                                    )
                                })}
                            </ItemGroup>
                        </div>
                    </div>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={onApply} disabledReason={applyDisabledReason}>
                        Apply
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
