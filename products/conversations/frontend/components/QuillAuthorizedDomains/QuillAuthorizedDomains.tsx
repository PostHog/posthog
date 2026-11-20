import { IconPencil, IconTrash } from '@posthog/icons'
import { Button, Input, Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@posthog/quill'

export function QuillAuthorizedDomains({
    domains,
    isAddingDomain,
    editingDomainIndex,
    domainInputValue,
    saveDisabledReason,
    onDomainInputChange,
    onDomainInputKeyDown,
    onSave,
    onCancel,
    onEdit,
    onRemove,
}: {
    domains: string[]
    isAddingDomain: boolean
    editingDomainIndex: number | null
    domainInputValue: string
    saveDisabledReason: string | undefined
    onDomainInputChange: (value: string) => void
    onDomainInputKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void
    onSave: () => void
    onCancel: () => void
    onEdit: (index: number) => void
    onRemove: (domain: string, index: number) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {domains.length === 0 && !isAddingDomain && (
                <Item variant="outline" size="sm">
                    <ItemContent>
                        <ItemTitle>No domains configured.</ItemTitle>
                        <ItemDescription>
                            The widget and API will be accessible on all domains. Add domains to limit where they
                            appear.
                        </ItemDescription>
                        <ItemTitle>Ticket recovery is disabled until a domain is added.</ItemTitle>
                        <ItemDescription>
                            Recovering tickets by email requires at least one authorized domain so the recovery link can
                            only point to a site you control.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {(isAddingDomain || editingDomainIndex !== null) && (
                <div className="flex flex-col gap-2">
                    <Input
                        autoFocus
                        value={domainInputValue}
                        onChange={(event) => onDomainInputChange(event.target.value)}
                        placeholder="https://example.com or https://*.example.com"
                        aria-label="Domain"
                        onKeyDown={onDomainInputKeyDown}
                    />
                    <div className="flex flex-wrap gap-2">
                        <Button variant="primary" onClick={onSave} disabledReason={saveDisabledReason}>
                            Save
                        </Button>
                        <Button variant="outline" onClick={onCancel}>
                            Cancel
                        </Button>
                    </div>
                </div>
            )}

            {domains.length > 0 && (
                <ItemGroup>
                    {domains.map((domain, index) =>
                        editingDomainIndex === index ? null : (
                            <Item key={index} variant="outline" size="sm">
                                <ItemContent className="min-w-0">
                                    <ItemTitle title={domain} className="truncate">
                                        {domain}
                                    </ItemTitle>
                                </ItemContent>
                                <ItemActions className="shrink-0 gap-1">
                                    <Button size="icon" aria-label="Edit" tooltip="Edit" onClick={() => onEdit(index)}>
                                        <IconPencil />
                                    </Button>
                                    <Button
                                        size="icon"
                                        aria-label="Remove domain"
                                        tooltip="Remove domain"
                                        onClick={() => onRemove(domain, index)}
                                    >
                                        <IconTrash />
                                    </Button>
                                </ItemActions>
                            </Item>
                        )
                    )}
                </ItemGroup>
            )}
        </div>
    )
}
