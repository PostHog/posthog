import { useActions, useValues } from 'kea'

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
    FieldDescription,
    FieldGroup,
    FieldLabel,
    Input,
    Textarea,
} from '@posthog/quill'

import { cloudImagesLogic } from './cloudImagesLogic'
import { QuillVisibilityToggleGroup } from './QuillVisibilityToggleGroup'

export function QuillCloudImageModal(): JSX.Element | null {
    const { draft, draftSaving, draftError } = useValues(cloudImagesLogic)
    const { updateDraft, closeDraft, createImage } = useActions(cloudImagesLogic)

    if (!draft) {
        return null
    }

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && closeDraft()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>New image</DialogTitle>
                    <DialogDescription>
                        A builder agent installs your tools in a sandbox and saves the result as an image. Cloud runs
                        that use it start with those tools ready.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor="cloud-image-name">Name</FieldLabel>
                            <Input
                                id="cloud-image-name"
                                value={draft.name}
                                onChange={(event) => updateDraft({ name: event.target.value })}
                                placeholder="For example: Node 22 with ripgrep"
                                autoFocus
                            />
                        </Field>
                        <Field>
                            <FieldLabel htmlFor="cloud-image-description">What the image needs</FieldLabel>
                            <Textarea
                                id="cloud-image-description"
                                value={draft.description}
                                onChange={(event) => updateDraft({ description: event.target.value })}
                                rows={3}
                                placeholder="For example: Node 22, pnpm, and ripgrep. Run pnpm install for the web app."
                            />
                        </Field>
                        <Field>
                            <FieldLabel htmlFor="cloud-image-repository">Repository (optional)</FieldLabel>
                            <Input
                                id="cloud-image-repository"
                                value={draft.repository}
                                onChange={(event) => updateDraft({ repository: event.target.value })}
                                placeholder="org/repo"
                            />
                            <FieldDescription>
                                The builder agent clones it to check that its dependencies install.
                            </FieldDescription>
                        </Field>
                        <QuillVisibilityToggleGroup
                            isPrivate={draft.private}
                            onChange={(isPrivate) => updateDraft({ private: isPrivate })}
                        />
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeDraft} disabledReason={draftSaving ? 'Saving' : undefined}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={createImage}
                        loading={draftSaving}
                        disabledReason={draftError ?? undefined}
                        data-attr="cloud-image-create"
                    >
                        Start building
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
