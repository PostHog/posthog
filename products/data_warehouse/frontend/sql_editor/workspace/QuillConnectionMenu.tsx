import { IconChevronDown, IconGear } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'
import { newInternalTab } from 'lib/utils/newInternalTab'
import {
    MANAGED_TRINO_CONNECTION,
    useConnectionSelectorState,
} from 'scenes/data-warehouse/editor/useConnectionSelectorState'

import {
    ADD_DIRECT_CONNECTION_PREFIX,
    CONFIGURE_SOURCES,
    type ConnectionSelectOption,
    POSTHOG_WAREHOUSE,
} from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

const isAction = (value: string | undefined): boolean =>
    !!value && (value === CONFIGURE_SOURCES || value.startsWith(ADD_DIRECT_CONNECTION_PREFIX))

function SourceIcon({ src }: { src?: string }): JSX.Element | null {
    return src ? (
        <img src={src} alt="" width={16} height={16} className="size-4 shrink-0 rounded object-contain" />
    ) : null
}

function findOption(options: ConnectionSelectOption[], value: string | null): ConnectionSelectOption | undefined {
    for (const option of options) {
        if (option.value === value) {
            return option
        }
        const nested = option.options ? findOption(option.options, value) : undefined
        if (nested) {
            return nested
        }
    }
    return undefined
}

export function QuillConnectionMenu({ tabId, className }: { tabId: string; className?: string }): JSX.Element {
    const { value, groups, showManagedTrino, managedTrinoDisabledReason, select } = useConnectionSelectorState(tabId)

    const allOptions = groups.flatMap((group) => group.options)
    const posthogOption = findOption(allOptions, POSTHOG_WAREHOUSE)
    const selected =
        value === MANAGED_TRINO_CONNECTION
            ? { label: 'PostHog (Trino)', iconSrc: posthogOption?.iconSrc }
            : findOption(allOptions, value)
    const selectedManagementUrl = selected && 'managementUrl' in selected ? selected.managementUrl : undefined

    const connectionGroups = groups
        .map((group) => group.options.filter((option) => !option.hidden && !option.options && !isAction(option.value)))
        .filter((options) => options.length > 0)
    const actionOptions = groups.flatMap((group) =>
        group.options.filter((option) => !option.hidden && (option.options || isAction(option.value)))
    )

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        className={cn('min-w-0 justify-start', className)}
                        data-attr="sql-editor-connection-selector"
                    />
                }
            >
                <SourceIcon src={selected?.iconSrc} />
                <span className="min-w-0 truncate">{selected?.label ?? 'Choose a connection'}</span>
                <IconChevronDown className="ms-auto" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup value={value ?? undefined} onValueChange={(next) => select(next as string)}>
                    {connectionGroups.map((options, index) => (
                        <DropdownMenuGroup key={index}>
                            {index > 0 ? <DropdownMenuSeparator /> : null}
                            {options.flatMap((option) => {
                                const row = (
                                    <DropdownMenuRadioItem
                                        key={option.value}
                                        value={option.value as string}
                                        disabledReason={
                                            option.disabled ? 'This connection is not available' : undefined
                                        }
                                    >
                                        <SourceIcon src={option.iconSrc} />
                                        {option.label}
                                    </DropdownMenuRadioItem>
                                )
                                if (option.value !== POSTHOG_WAREHOUSE || !showManagedTrino) {
                                    return [row]
                                }
                                return [
                                    row,
                                    <DropdownMenuRadioItem
                                        key={MANAGED_TRINO_CONNECTION}
                                        value={MANAGED_TRINO_CONNECTION}
                                        disabledReason={managedTrinoDisabledReason}
                                    >
                                        <SourceIcon src={option.iconSrc} />
                                        PostHog (Trino)
                                    </DropdownMenuRadioItem>,
                                ]
                            })}
                        </DropdownMenuGroup>
                    ))}
                </DropdownMenuRadioGroup>
                {selectedManagementUrl ? (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                            {/* The Lemon picker puts a gear on every connection row. A menu row can't hold a
                                second button, so the quill menu offers settings for the chosen connection. */}
                            <DropdownMenuItem
                                onClick={() => newInternalTab(selectedManagementUrl)}
                                data-attr="connection-selector-source-settings"
                            >
                                <IconGear />
                                {`${selected?.label} settings`}
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    </>
                ) : null}
                {actionOptions.length > 0 ? <DropdownMenuSeparator /> : null}
                <DropdownMenuGroup>
                    {actionOptions.map((option) =>
                        option.options ? (
                            <DropdownMenuSub key={option.label}>
                                <DropdownMenuSubTrigger>{option.label}</DropdownMenuSubTrigger>
                                <DropdownMenuSubContent>
                                    {option.options.map((child) => (
                                        <DropdownMenuItem key={child.value} onClick={() => select(child.value ?? null)}>
                                            <SourceIcon src={child.iconSrc} />
                                            {child.label}
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                        ) : (
                            <DropdownMenuItem key={option.value} onClick={() => select(option.value ?? null)}>
                                {option.label}
                            </DropdownMenuItem>
                        )
                    )}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
