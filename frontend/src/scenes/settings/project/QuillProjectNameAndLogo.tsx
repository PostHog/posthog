import { MouseEvent } from 'react'

import { IconUpload, IconX } from '@posthog/icons'
import { LemonFileInput } from '@posthog/lemon-ui'
import { Button, Field, FieldError, Input } from '@posthog/quill'

import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'

export function QuillProjectNameAndLogo({
    projectName,
    projectId,
    name,
    onNameChange,
    logoMediaId,
    onRemoveLogo,
    filesToUpload,
    onFilesToUploadChange,
    uploading,
    restrictionReason,
    nameError,
    onSave,
    saveDisabledReason,
    saving,
}: {
    projectName: string | undefined
    projectId: number | undefined
    name: string
    onNameChange: (name: string) => void
    logoMediaId: string | null
    onRemoveLogo: (e: MouseEvent) => void
    filesToUpload: File[]
    onFilesToUploadChange: (files: File[]) => void
    uploading: boolean
    restrictionReason: string | null
    nameError: string | undefined
    onSave: () => void
    saveDisabledReason: string | null
    saving: boolean
}): JSX.Element {
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
                            name={projectName || '?'}
                            entityId={projectId || 1}
                            mediaId={logoMediaId}
                            size="xlarge"
                            outlinedLettermark
                        />
                        {logoMediaId && !restrictionReason && (
                            <div className="absolute -inset-2 group">
                                <Button
                                    size="icon-xs"
                                    aria-label="Remove logo"
                                    tooltip="Remove logo"
                                    onClick={onRemoveLogo}
                                    className="absolute right-0 top-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                                    data-attr="project-logo-remove"
                                >
                                    <IconX />
                                </Button>
                            </div>
                        )}
                        <Button disabledReason={restrictionReason} data-attr="project-logo-upload">
                            <IconUpload />
                            Upload
                        </Button>
                    </div>
                }
            />
            <div className="flex-1 min-w-60 max-w-120 flex flex-col gap-3">
                <Field data-invalid={nameError ? true : undefined}>
                    <Input
                        value={name}
                        onChange={(event) => onNameChange(event.target.value)}
                        disabledReason={restrictionReason}
                        placeholder="Project name"
                        aria-label="Project name"
                        aria-invalid={nameError ? true : undefined}
                        data-attr="project-name-input-settings"
                    />
                    {nameError && <FieldError>{nameError}</FieldError>}
                </Field>
                <div>
                    <Button
                        variant="primary"
                        onClick={onSave}
                        disabledReason={saveDisabledReason}
                        loading={saving}
                        data-attr="project-name-and-logo-save"
                    >
                        Save
                    </Button>
                </div>
            </div>
        </div>
    )
}
