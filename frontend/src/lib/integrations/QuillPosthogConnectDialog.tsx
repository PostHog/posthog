import { useId } from 'react'

import { IconSearch } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import type { ScopePickerRow } from 'lib/scopes'

export interface QuillPosthogConnectDialogProps<TRegion extends string> {
    isOpen: boolean
    onClose: () => void
    region: TRegion
    regionOptions: { value: TRegion; label: string }[]
    onRegionChange: (region: TRegion) => void
    presetOptions: { value: string; label: string }[]
    onApplyPreset: (preset: string) => void
    searchTerm: string
    onSearchTermChange: (searchTerm: string) => void
    scopeRows: ScopePickerRow[]
    onScopeActionChange: (key: string, action: string) => void
    connectDisabledReason: string | undefined
    onConnect: () => void
}

export function QuillPosthogConnectDialog<TRegion extends string>({
    isOpen,
    onClose,
    region,
    regionOptions,
    onRegionChange,
    presetOptions,
    onApplyPreset,
    searchTerm,
    onSearchTermChange,
    scopeRows,
    onScopeActionChange,
    connectDisabledReason,
    onConnect,
}: QuillPosthogConnectDialogProps<TRegion>): JSX.Element {
    const idPrefix = useId()

    const regionId = `${idPrefix}-region`

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Connect a PostHog project</DialogTitle>
                    <DialogDescription>
                        You'll be sent to the target PostHog to sign in and approve the access below.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Field>
                            <FieldLabel htmlFor={regionId}>PostHog region</FieldLabel>
                            <Select value={region} onValueChange={(value) => value && onRegionChange(value as TRegion)}>
                                <SelectTrigger id={regionId}>
                                    <SelectValue>
                                        {(value: TRegion) =>
                                            regionOptions.find((option) => option.value === value)?.label
                                        }
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    {regionOptions.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                        <div className="flex flex-col gap-2">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                                    Access to grant
                                </Text>
                                <Select<string> value={null} onValueChange={(value) => value && onApplyPreset(value)}>
                                    <SelectTrigger aria-label="Apply a preset">
                                        <SelectValue placeholder="Apply a preset" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {presetOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <InputGroup size="sm">
                                <InputGroupAddon align="inline-start">
                                    <IconSearch />
                                </InputGroupAddon>
                                <InputGroupInput
                                    type="search"
                                    placeholder="Search scopes..."
                                    aria-label="Search scopes"
                                    value={searchTerm}
                                    onChange={(event) => onSearchTermChange(event.target.value)}
                                />
                            </InputGroup>
                            <div>
                                {scopeRows.length === 0 ? (
                                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                        No scopes match "{searchTerm}"
                                    </Text>
                                ) : (
                                    scopeRows.map((row) => (
                                        <ScopeAccessRow key={row.key} row={row} onChange={onScopeActionChange} />
                                    ))
                                )}
                            </div>
                        </div>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="primary" onClick={onConnect} disabledReason={connectDisabledReason}>
                        {`Connect ${region}`}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
