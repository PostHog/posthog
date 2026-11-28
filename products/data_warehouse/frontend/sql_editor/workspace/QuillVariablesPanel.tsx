import { useState } from 'react'

import { IconBrackets, IconEllipsis, IconExternal, IconPlus, IconSearch } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    MenuLabel,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    NEW_VARIABLE_TYPES,
    QueryVariablesState,
    useQueryVariablesState,
} from 'scenes/data-warehouse/editor/useQueryVariablesState'
import { urls } from 'scenes/urls'

import { VariableInput } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { Variable } from '~/queries/nodes/DataVisualization/types'

function formatVariableValue(variable: Variable): string {
    if (variable.isNull) {
        return 'null'
    }
    const value = variable.value ?? variable.default_value
    if (Array.isArray(value)) {
        return value.join(', ')
    }
    return value === undefined || value === '' ? 'No value' : String(value)
}

function VariableRowMenu({
    variable,
    state,
    canRemove,
}: {
    variable: Variable
    state: QueryVariablesState
    canRemove: boolean
}): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon-sm"
                        aria-label={`More for ${variable.name}`}
                        tooltip="More"
                        className="opacity-0 group-hover/variable:opacity-100 focus-visible:opacity-100 data-[popup-open]:opacity-100"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                    <DropdownMenuItem onClick={() => state.insert(variable)}>Insert into query</DropdownMenuItem>
                    <DropdownMenuItem onClick={() => state.copyCode(variable)}>Copy variable code</DropdownMenuItem>
                    <DropdownMenuItem onClick={() => state.edit(variable)}>Edit variable…</DropdownMenuItem>
                </DropdownMenuGroup>
                {canRemove ? (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                            <DropdownMenuItem variant="destructive" onClick={() => state.remove(variable)}>
                                Remove from this query
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    </>
                ) : null}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function VariableValueRow({
    variable,
    state,
    canRemove,
}: {
    variable: Variable
    state: QueryVariablesState
    canRemove: boolean
}): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <div className="group/variable flex items-center gap-1 rounded-sm pe-1 hover:bg-fill-hover has-[[data-popup-open]]:bg-fill-hover">
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <button
                            type="button"
                            className="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-sm px-2 py-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                        />
                    }
                >
                    <span className="flex w-full min-w-0 items-center gap-2">
                        <Text size="xs" className="m-0 min-w-0 truncate font-medium">
                            {variable.name}
                        </Text>
                        <Badge className="ms-auto">{variable.type}</Badge>
                    </span>
                    <span className="w-full min-w-0 truncate font-mono text-xxs text-muted-foreground" translate="no">
                        {formatVariableValue(variable)}
                    </span>
                </PopoverTrigger>
                <PopoverContent side="left" align="start" className="w-80 p-2">
                    <VariableInput
                        variable={variable}
                        showEditingUI={false}
                        onChange={(_, value, isNull) => state.setValue(variable, value, isNull)}
                        closePopover={() => setOpen(false)}
                    />
                </PopoverContent>
            </Popover>
            <VariableRowMenu variable={variable} state={state} canRemove={canRemove} />
        </div>
    )
}

export function QuillVariablesPanel({ disabledReason }: { disabledReason?: string }): JSX.Element {
    const state = useQueryVariablesState()

    if (!state.showEditingUI || disabledReason) {
        return (
            <Empty className="h-full">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconBrackets />
                    </EmptyMedia>
                    <EmptyTitle>Variables aren't available here</EmptyTitle>
                    <EmptyDescription>{disabledReason ?? 'This query is read-only.'}</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    const hasAnyVariable = state.usedInQuery.length + state.unusedWithValues.length + state.other.length > 0

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex items-center gap-1 p-2">
                <InputGroup size="sm" className="flex-1">
                    <InputGroupAddon>
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        placeholder="Search variables"
                        aria-label="Search variables"
                        value={state.searchTerm}
                        onChange={(event) => state.setSearchTerm(event.target.value)}
                        data-attr="insight-variable-search"
                    />
                </InputGroup>
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon"
                                aria-label="New variable"
                                tooltip="New variable"
                                data-attr="sql-editor-new-variable"
                            />
                        }
                    >
                        <IconPlus />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuGroup>
                            <MenuLabel>New variable</MenuLabel>
                            {NEW_VARIABLE_TYPES.map((type) => (
                                <DropdownMenuItem key={type} onClick={() => state.create(type)}>
                                    {type}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto scroll-mask-y-4 scroll-py-4 px-2 pb-2">
                {state.loading ? (
                    <div className="flex flex-col gap-2 p-2">
                        <Skeleton className="h-8" />
                        <Skeleton className="h-8" />
                        <Skeleton className="h-8" />
                    </div>
                ) : !hasAnyVariable ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyMedia variant="icon">
                                <IconBrackets />
                            </EmptyMedia>
                            <EmptyTitle>{state.searchTerm ? 'No variables match' : 'No variables yet'}</EmptyTitle>
                            <EmptyDescription>
                                Variables let you change a value in the query without editing the SQL. Create one, then
                                insert it as <code>{'{variables.name}'}</code>.
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
                    <div className="flex flex-col gap-3">
                        {state.usedInQuery.length > 0 ? (
                            <section className="flex flex-col gap-0.5">
                                <MenuLabel>In this query</MenuLabel>
                                {state.usedInQuery.map((variable) => (
                                    <VariableValueRow
                                        key={variable.id}
                                        variable={variable}
                                        state={state}
                                        canRemove={false}
                                    />
                                ))}
                            </section>
                        ) : null}
                        {state.unusedWithValues.length > 0 ? (
                            <section className="flex flex-col gap-0.5">
                                <MenuLabel>No longer in the query</MenuLabel>
                                {state.unusedWithValues.map((variable) => (
                                    <VariableValueRow key={variable.id} variable={variable} state={state} canRemove />
                                ))}
                            </section>
                        ) : null}
                        {state.other.length > 0 ? (
                            <section className="flex flex-col gap-0.5">
                                <MenuLabel>Insert a variable</MenuLabel>
                                {state.other.map((variable) => (
                                    <Button
                                        key={variable.id}
                                        left
                                        size="row"
                                        className="w-full"
                                        tooltip="Insert into the query at the cursor"
                                        onClick={() => state.insert(variable)}
                                    >
                                        <span className="min-w-0 truncate">{variable.name}</span>
                                        <span className="min-w-0 truncate font-mono text-xxs text-muted-foreground">
                                            {variable.code_name}
                                        </span>
                                        <Badge className="ms-auto">{variable.type}</Badge>
                                    </Button>
                                ))}
                            </section>
                        ) : null}
                    </div>
                )}
            </div>
            <div className="border-t p-2">
                <Button
                    variant="link-muted"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.variables()} target="_blank" />}
                    data-attr="sql-editor-manage-variables"
                >
                    Manage SQL variables
                    <IconExternal />
                </Button>
            </div>
        </div>
    )
}
