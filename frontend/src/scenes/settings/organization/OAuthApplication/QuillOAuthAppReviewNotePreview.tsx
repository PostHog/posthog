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
    Item,
    ItemContent,
    Text,
} from '@posthog/quill'

import { OrganizationOAuthApplicationDetailApi } from '~/generated/core/api.schemas'

import { REVIEW_NOTE_SUBMIT_LABELS } from '../oauthAppProvisioningStatus'
import { oauthAppReviewNoteLogic } from './oauthAppReviewNoteLogic'

export function QuillOAuthAppReviewNotePreview({ app }: { app: OrganizationOAuthApplicationDetailApi }): JSX.Element {
    const logic = oauthAppReviewNoteLogic({ appId: app.id })
    const { isNotePreviewOpen, reviewNote, isReviewNoteSubmitting } = useValues(logic)
    const { closeNotePreview, submitReviewNote } = useActions(logic)

    return (
        <Dialog
            open={isNotePreviewOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeNotePreview()
                }
            }}
        >
            <DialogContent className="sm:max-w-140">
                <DialogHeader>
                    <DialogTitle>Review your note</DialogTitle>
                    <DialogDescription>
                        PostHog staff read your note in the review of this application, next to what PostHog read from
                        your metadata document.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="semibold" render={<span />}>
                            Your note
                        </Text>
                        <Item variant="muted" size="sm">
                            <ItemContent>
                                <Text size="xs" render={<p className="m-0 whitespace-pre-wrap" />}>
                                    {reviewNote.note}
                                </Text>
                            </ItemContent>
                        </Item>
                    </div>
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="semibold" render={<span />}>
                            Sent with it
                        </Text>
                        <ul className="m-0 pl-5 list-disc">
                            <Text size="xs" render={<li />}>{`The application's client ID: ${app.client_id}`}</Text>
                            <Text size="xs" render={<li />}>
                                Your email, so staff know who answered
                            </Text>
                            <Text size="xs" render={<li />}>
                                The review's history and your metadata document, which staff already have
                            </Text>
                        </ul>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeNotePreview} disabled={isReviewNoteSubmitting}>
                        Keep editing
                    </Button>
                    <Button
                        variant="primary"
                        onClick={submitReviewNote}
                        loading={isReviewNoteSubmitting}
                        data-attr="oauth-app-review-note-submit"
                    >
                        {REVIEW_NOTE_SUBMIT_LABELS[app.provisioning_status] ?? 'Send note'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
