import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Textarea,
} from '@posthog/quill'

import { CupedModal } from 'products/experiments/frontend/modals/CupedModal/CupedModal'
import { StatsMethodModal } from 'products/experiments/frontend/modals/StatsMethodModal/StatsMethodModal'

import { HYPOTHESIS_PLACEHOLDER, useHypothesisDescriptionDraft } from './hypothesisPanel'

export function QuillHypothesisModals(): JSX.Element {
    const { isOpen, close, draft, setDraft, save } = useHypothesisDescriptionDraft()

    return (
        <>
            <StatsMethodModal />
            <CupedModal />
            <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
                <DialogContent data-attr="experiment-hypothesis-modal">
                    <DialogHeader>
                        <DialogTitle>Edit hypothesis</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <Field>
                            <FieldLabel htmlFor="experiment-hypothesis-input" className="sr-only">
                                Hypothesis
                            </FieldLabel>
                            <Textarea
                                id="experiment-hypothesis-input"
                                value={draft}
                                onChange={(event) => setDraft(event.target.value)}
                                placeholder={HYPOTHESIS_PLACEHOLDER}
                                rows={6}
                                maxLength={3000}
                            />
                        </Field>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={close}>
                            Cancel
                        </Button>
                        <Button variant="primary" onClick={save}>
                            Save
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}
