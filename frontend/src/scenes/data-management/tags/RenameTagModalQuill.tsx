import { useActions, useValues } from 'kea'

import {
    Button,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
    Item,
    ItemContent,
} from '@posthog/quill'

import { TAG_REFERENCE_WARNING, tagsLogic } from './tagsLogic'

export function RenameTagModalQuill(): JSX.Element | null {
    const { tagToRename, renameName, mutationLoading, mutationError } = useValues(tagsLogic)
    const { closeModals, setRenameName, submitRename } = useActions(tagsLogic)
    if (!tagToRename) {
        return null
    }
    return (
        <Credenza
            open
            onOpenChange={(open) => {
                if (!open && !mutationLoading) {
                    closeModals()
                }
            }}
        >
            <CredenzaContent className="ph-no-capture">
                <CredenzaHeader>
                    <CredenzaTitle>Rename tag</CredenzaTitle>
                </CredenzaHeader>
                <CredenzaBody viewportClassName="flex flex-col gap-4">
                    <Field>
                        <FieldLabel htmlFor="rename-tag-name">Tag name</FieldLabel>
                        <Input
                            id="rename-tag-name"
                            value={renameName}
                            onChange={(event) => setRenameName(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter') {
                                    event.preventDefault()
                                    submitRename()
                                }
                            }}
                            maxLength={255}
                            disabledReason={mutationLoading ? 'Wait for the rename to finish.' : undefined}
                            autoFocus
                            data-attr="tag-management-rename-name"
                        />
                        {mutationError && <FieldError>{mutationError}</FieldError>}
                    </Field>
                    <Item tone="warning">
                        <ItemContent>{TAG_REFERENCE_WARNING}</ItemContent>
                    </Item>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button
                        variant="outline"
                        onClick={closeModals}
                        disabledReason={mutationLoading ? 'Wait for the rename to finish.' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={mutationLoading}
                        onClick={submitRename}
                        disabledReason={!renameName.trim() ? 'Enter a tag name.' : undefined}
                        data-attr="tag-management-rename-confirm"
                    >
                        Rename tag
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
