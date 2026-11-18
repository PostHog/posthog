import { useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, Heading, ItemGroup, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'

import { AccessControlLevel, AvailableFeature } from '~/types'

import { accessControlLogic } from '../accessControlLogic'
import { AddAccessOption, QuillAddAccessDialog } from './QuillAddAccessDialog'

interface QuillAccessSectionProps {
    title: string
    /** Feeds the add button's data-attr, e.g. "member" → `access-control-add-member`. */
    subject: 'member' | 'role'
    emptyText: string
    children: React.ReactNode[]
    feature: AvailableFeature
    placeholder: string
    nothingToAddText: string
    options: AddAccessOption[]
    onAdd: (keys: string[], level: AccessControlLevel) => Promise<void>
}

export function QuillAccessSection({
    title,
    subject,
    emptyText,
    children,
    feature,
    placeholder,
    nothingToAddText,
    options,
    onAdd,
}: QuillAccessSectionProps): JSX.Element {
    const { canEditAccessControls, accessControlsLoading: loading } = useValues(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const [dialogOpen, setDialogOpen] = useState(false)
    const addDisabledReason = canEditAccessControls ? undefined : 'You cannot edit this'
    const onAddClick = (): void => setDialogOpen(true)

    return (
        <section className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    {title}
                </Heading>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="outline"
                                disabled={!!addDisabledReason}
                                onClick={onAddClick}
                                data-attr={`access-control-add-${subject}`}
                            />
                        }
                    >
                        <IconPlus />
                        Add
                    </TooltipTrigger>
                    {addDisabledReason && <TooltipContent>{addDisabledReason}</TooltipContent>}
                </Tooltip>
            </div>
            {loading && !children.length ? (
                <div className="flex flex-col gap-1">
                    <Skeleton className="h-11" />
                    <Skeleton className="h-11 opacity-70" />
                </div>
            ) : !children.length ? (
                <Text size="xs" variant="muted">
                    {emptyText}
                </Text>
            ) : (
                <ItemGroup combined>{children}</ItemGroup>
            )}
            <QuillAddAccessDialog
                open={dialogOpen}
                onOpenChange={setDialogOpen}
                pickerLabel={title}
                placeholder={placeholder}
                emptyText={nothingToAddText}
                options={options}
                onAdd={async (keys, level) => {
                    if (guardAvailableFeature(feature)) {
                        await onAdd(keys, level)
                        setDialogOpen(false)
                    }
                }}
            />
        </section>
    )
}
