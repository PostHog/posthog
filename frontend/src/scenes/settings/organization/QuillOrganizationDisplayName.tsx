import { MouseEvent, useId } from 'react'

import { IconUpload, IconX } from '@posthog/icons'
import { LemonFileInput } from '@posthog/lemon-ui'
import { Button, Field, FieldLabel, Input } from '@posthog/quill'

import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'

import type { OrganizationType } from '~/types'

export function QuillOrganizationDisplayName({
    organization,
    name,
    onNameChange,
    logoMediaId,
    onResetLogo,
    filesToUpload,
    onFilesToUploadChange,
    uploading,
    restrictionReason,
    saveDisabledReason,
    saving,
    onSave,
}: {
    organization: OrganizationType | null
    name: string
    onNameChange: (name: string) => void
    logoMediaId: string | null
    onResetLogo: (event: MouseEvent) => void
    filesToUpload: File[]
    onFilesToUploadChange: (files: File[]) => void
    uploading: boolean
    restrictionReason: string | null
    saveDisabledReason: string | null | undefined
    saving: boolean
    onSave: (event: MouseEvent) => void
}): JSX.Element {
    const nameInputId = useId()

    return (
        <div className="flex flex-wrap gap-6 items-start">
            <LemonFileInput
                accept="image/*"
                multiple={false}
                onChange={onFilesToUploadChange}
                loading={uploading}
                value={filesToUpload}
                disabledReason={restrictionReason}
                callToAction={
                    <div className="relative flex flex-col items-center gap-1">
                        <UploadedLogo
                            name={organization?.name || '?'}
                            entityId={organization?.id || 1}
                            mediaId={logoMediaId}
                            size="xlarge"
                        />
                        {logoMediaId && (
                            <div className="absolute -inset-2 group">
                                <Button
                                    size="icon-xs"
                                    aria-label="Reset back to lettermark"
                                    tooltip="Reset back to lettermark"
                                    onClick={onResetLogo}
                                    className="group-hover:flex hidden absolute right-0 top-0"
                                >
                                    <IconX />
                                </Button>
                            </div>
                        )}
                        <span className="flex items-center gap-1 text-muted-foreground text-xs">
                            <IconUpload className="text-sm" />
                            Upload
                        </span>
                    </div>
                }
            />
            <div className="flex flex-1 flex-col items-start gap-2 min-w-60 max-w-120">
                <Field>
                    <FieldLabel htmlFor={nameInputId} className="sr-only">
                        Organization name
                    </FieldLabel>
                    <Input
                        id={nameInputId}
                        value={name}
                        onChange={(event) => onNameChange(event.target.value)}
                        disabledReason={restrictionReason}
                        data-attr="organization-name-input-settings"
                        placeholder="Organization name"
                    />
                </Field>
                <Button variant="primary" onClick={onSave} disabledReason={saveDisabledReason} loading={saving}>
                    Save
                </Button>
            </div>
        </div>
    )
}
