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
    FieldError,
    FieldLabel,
    Textarea,
} from '@posthog/quill'

import { dashboardV2Logic } from './dashboardV2Logic'

export function DashboardV2JsonDialog(): JSX.Element {
    const { jsonDraft, saving, saveErrors } = useValues(dashboardV2Logic)
    const { closeJsonDialog, setJsonDraft, saveJsonDraft } = useActions(dashboardV2Logic)

    return (
        <Dialog open={jsonDraft !== null} onOpenChange={(open: boolean) => !open && closeJsonDialog()}>
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>Edit dashboard JSON</DialogTitle>
                    <DialogDescription>
                        A dashboard is one document. Saving publishes it as a new version.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <Field>
                        <FieldLabel htmlFor="dashboard-v2-json">Dashboard document</FieldLabel>
                        <Textarea
                            id="dashboard-v2-json"
                            className="min-h-96 font-mono"
                            spellCheck={false}
                            translate="no"
                            value={jsonDraft ?? ''}
                            onChange={(event) => setJsonDraft(event.target.value)}
                            data-attr="dashboard-v2-json-input"
                        />
                        {saveErrors.map((error) => (
                            <FieldError key={error}>{error}</FieldError>
                        ))}
                    </Field>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={() => closeJsonDialog()}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={saving}
                        onClick={() => saveJsonDraft()}
                        data-attr="dashboard-v2-json-save"
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
