import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldError,
    FieldGroup,
    FieldLabel,
    Input,
    Textarea,
} from '@posthog/quill'

import { dashboardV2ListLogic } from './dashboardV2ListLogic'

export function NewDashboardV2Dialog(): JSX.Element {
    const { newDialogOpen, createdDashboardLoading, createErrors } = useValues(dashboardV2ListLogic)
    const { setNewDialogOpen, createDashboard } = useActions(dashboardV2ListLogic)
    const [title, setTitle] = useState('')
    const [json, setJson] = useState('')

    useEffect(() => {
        if (!newDialogOpen) {
            setTitle('')
            setJson('')
        }
    }, [newDialogOpen])

    const importing = !!json.trim()

    return (
        <Dialog open={newDialogOpen} onOpenChange={(open: boolean) => setNewDialogOpen(open)}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>New dashboard</DialogTitle>
                    <DialogDescription>Start with an empty dashboard, or import one from JSON.</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor="dashboard-v2-new-title">Name</FieldLabel>
                            <Input
                                id="dashboard-v2-new-title"
                                autoFocus
                                placeholder="Checkout health"
                                disabled={importing}
                                value={title}
                                onChange={(event) => setTitle(event.target.value)}
                                data-attr="dashboard-v2-new-title"
                            />
                        </Field>
                        <Collapsible>
                            <CollapsibleTrigger>Advanced options</CollapsibleTrigger>
                            <CollapsibleContent className="pt-2">
                                <Field>
                                    <FieldLabel htmlFor="dashboard-v2-new-json">Import from JSON</FieldLabel>
                                    <Textarea
                                        id="dashboard-v2-new-json"
                                        className="min-h-40 font-mono"
                                        spellCheck={false}
                                        translate="no"
                                        value={json}
                                        onChange={(event) => setJson(event.target.value)}
                                        data-attr="dashboard-v2-new-json"
                                    />
                                    <FieldDescription>
                                        Paste a dashboard document. Its own title replaces the name above.
                                    </FieldDescription>
                                </Field>
                            </CollapsibleContent>
                        </Collapsible>
                        {createErrors.map((error) => (
                            <FieldError key={error}>{error}</FieldError>
                        ))}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={() => setNewDialogOpen(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={createdDashboardLoading}
                        disabledReason={!importing && !title.trim() ? 'Give the dashboard a name' : undefined}
                        onClick={() => createDashboard({ title: title.trim(), json })}
                        data-attr="dashboard-v2-new-create"
                    >
                        {importing ? 'Import dashboard' : 'Create dashboard'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
