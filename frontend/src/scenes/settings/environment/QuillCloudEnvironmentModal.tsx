import { useActions, useValues } from 'kea'

import {
    Button,
    Checkbox,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    Input,
    RadioGroup,
    RadioGroupItem,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import { SandboxEnvironmentNetworkAccessLevelEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { NETWORK_ACCESS_COPY } from './cloudEnvironmentNetworkAccess'
import { cloudEnvironmentsLogic } from './cloudEnvironmentsLogic'
import { cloudImagesLogic } from './cloudImagesLogic'
import { QuillVisibilityToggleGroup } from './QuillVisibilityToggleGroup'

// Select items need a non-null value, so the default image gets a sentinel that maps back to null.
const DEFAULT_IMAGE_VALUE = '__default__'

export function QuillCloudEnvironmentModal(): JSX.Element | null {
    const { draft, draftSaving, draftError } = useValues(cloudEnvironmentsLogic)
    const { updateDraft, closeDraft, saveDraft } = useActions(cloudEnvironmentsLogic)
    const { readyImages, unavailable: imagesUnavailable } = useValues(cloudImagesLogic)

    if (!draft) {
        return null
    }

    const imageOptions = [
        { value: DEFAULT_IMAGE_VALUE, label: 'Default image' },
        ...readyImages.map((image) => ({ value: image.id, label: image.name })),
    ]

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && closeDraft()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{draft.id ? 'Edit environment' : 'New environment'}</DialogTitle>
                    <DialogDescription>
                        Cloud runs start in a sandbox. An environment sets which repositories it applies to and what the
                        sandbox can reach.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor="cloud-environment-name">Name</FieldLabel>
                            <Input
                                id="cloud-environment-name"
                                value={draft.name}
                                onChange={(event) => updateDraft({ name: event.target.value })}
                                placeholder="For example: Web app"
                                autoFocus
                            />
                        </Field>
                        <QuillVisibilityToggleGroup
                            isPrivate={draft.private}
                            onChange={(isPrivate) => updateDraft({ private: isPrivate })}
                        />
                        <Field>
                            <FieldLabel>Repositories</FieldLabel>
                            <TagsCombobox
                                value={draft.repositories}
                                onChange={(repositories) => updateDraft({ repositories })}
                                customValueNoun="repository"
                                placeholder="Type org/repo and press Enter"
                                className="w-full"
                            />
                            <FieldDescription>Leave empty to use this environment for any repository.</FieldDescription>
                        </Field>
                        <Field>
                            <FieldLabel>Network access</FieldLabel>
                            <RadioGroup
                                value={draft.network_access_level}
                                onValueChange={(level) =>
                                    updateDraft({
                                        network_access_level: level as SandboxEnvironmentNetworkAccessLevelEnumApi,
                                    })
                                }
                            >
                                {Object.values(SandboxEnvironmentNetworkAccessLevelEnumApi).map((level) => (
                                    <Field key={level} orientation="horizontal" className="items-start">
                                        <RadioGroupItem id={`cloud-environment-network-${level}`} value={level} />
                                        <FieldContent>
                                            <FieldLabel htmlFor={`cloud-environment-network-${level}`}>
                                                {NETWORK_ACCESS_COPY[level].label}
                                            </FieldLabel>
                                            <FieldDescription>
                                                {NETWORK_ACCESS_COPY[level].description}
                                            </FieldDescription>
                                        </FieldContent>
                                    </Field>
                                ))}
                            </RadioGroup>
                        </Field>
                        {imagesUnavailable ? null : (
                            <Field>
                                <FieldLabel htmlFor="cloud-environment-image">Image</FieldLabel>
                                <Select
                                    value={draft.custom_image_id ?? DEFAULT_IMAGE_VALUE}
                                    onValueChange={(value) =>
                                        updateDraft({
                                            custom_image_id: value === DEFAULT_IMAGE_VALUE ? null : (value as string),
                                        })
                                    }
                                >
                                    <SelectTrigger id="cloud-environment-image" className="w-full">
                                        <SelectValue>
                                            {(value: string) =>
                                                imageOptions.find((option) => option.value === value)?.label ?? value
                                            }
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {imageOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                <FieldDescription>
                                    Runs that use this environment start from this image.
                                </FieldDescription>
                            </Field>
                        )}
                        {draft.network_access_level === SandboxEnvironmentNetworkAccessLevelEnumApi.Custom ? (
                            <>
                                <Field>
                                    <FieldLabel>Allowed domains</FieldLabel>
                                    <TagsCombobox
                                        value={draft.allowed_domains}
                                        onChange={(allowed_domains) => updateDraft({ allowed_domains })}
                                        customValueNoun="domain"
                                        placeholder="Type a domain, such as api.example.com, and press Enter"
                                        className="w-full"
                                    />
                                </Field>
                                <Field orientation="horizontal">
                                    <Checkbox
                                        id="cloud-environment-default-domains"
                                        checked={draft.include_default_domains}
                                        onCheckedChange={(include_default_domains: boolean) =>
                                            updateDraft({ include_default_domains })
                                        }
                                    />
                                    <FieldLabel htmlFor="cloud-environment-default-domains">
                                        Also allow the trusted package sources (GitHub, npm, PyPI)
                                    </FieldLabel>
                                </Field>
                            </>
                        ) : null}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeDraft} disabledReason={draftSaving ? 'Saving' : undefined}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={saveDraft}
                        loading={draftSaving}
                        disabledReason={draftError ?? undefined}
                        data-attr="cloud-environment-save"
                    >
                        {draft.id ? 'Save' : 'Create environment'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
