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
} from '@posthog/quill'

import { savedDashboardLogic } from './savedDashboardLogic'

function ChangeList({ title, changes }: { title: string; changes: string[] }): JSX.Element {
    return (
        <section className="flex flex-col gap-1">
            <h3 className="text-sm font-semibold m-0">{title}</h3>
            {changes.length > 0 ? (
                <ul className="list-disc ps-5 m-0 text-sm">
                    {changes.map((change, index) => (
                        <li key={index}>{change}</li>
                    ))}
                </ul>
            ) : (
                <p className="text-sm text-muted-foreground m-0">No changes</p>
            )}
        </section>
    )
}

export function SaveConflictDialog(): JSX.Element | null {
    const { conflictChanges } = useValues(savedDashboardLogic)
    const { keepTheirVersion, keepMyVersion } = useActions(savedDashboardLogic)
    if (!conflictChanges) {
        return null
    }
    // The person has to pick a version, so the dialog has no close button and ignores Escape.
    return (
        <Dialog open onOpenChange={() => {}}>
            <DialogContent showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>Someone else saved this dashboard</DialogTitle>
                    <DialogDescription>
                        They saved it while you were editing. Choose which version to keep.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-4">
                    <ChangeList title="Their changes" changes={conflictChanges.theirs} />
                    <ChangeList title="Your changes" changes={conflictChanges.yours} />
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={keepTheirVersion} data-attr="dashboard-v2-conflict-keep-theirs">
                        Keep their version
                    </Button>
                    <Button variant="primary" onClick={keepMyVersion} data-attr="dashboard-v2-conflict-keep-mine">
                        Keep my version
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
