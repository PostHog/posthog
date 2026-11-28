import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import {
    Button,
    Credenza,
    CredenzaBody,
    CredenzaClose,
    CredenzaContent,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
} from '@posthog/quill'

import { accessControlsLogic } from './accessControlsLogic'
import { QuillAccessControlDetail } from './QuillAccessControlDetail'

export function QuillAccessDetailDialog({ projectId }: { projectId: string }): JSX.Element {
    const { accessDetailDialogOpen, panelEntry, panelEntryLoading, panelSubject } = useValues(
        accessControlsLogic({ projectId })
    )
    const { closeAccessDetailDialog } = useActions(accessControlsLogic({ projectId }))

    const noun = panelSubject?.scopeType === 'role' ? 'role' : 'member'

    return (
        <Credenza
            open={accessDetailDialogOpen}
            onOpenChange={(open) => {
                if (!open) {
                    closeAccessDetailDialog()
                }
            }}
        >
            <CredenzaContent className="sm:max-w-180">
                <CredenzaHeader>
                    <CredenzaTitle>{noun === 'role' ? 'Role access' : 'Member access'}</CredenzaTitle>
                </CredenzaHeader>
                <CredenzaBody>
                    {panelSubject && panelEntry ? (
                        <QuillAccessControlDetail
                            projectId={projectId}
                            scopeType={panelSubject.scopeType}
                            entry={panelEntry}
                        />
                    ) : panelEntryLoading ? (
                        <div className="flex flex-col gap-4">
                            <Skeleton className="h-10 w-full" />
                            <Skeleton className="h-24 w-full" />
                        </div>
                    ) : (
                        <Empty>
                            <EmptyHeader>
                                <EmptyMedia variant="icon">
                                    <IconLock />
                                </EmptyMedia>
                                <EmptyTitle>{noun === 'role' ? 'Role not found' : 'Member not found'}</EmptyTitle>
                                <EmptyDescription>
                                    This {noun} may have been removed, or you may not have access to it. Pick another
                                    from the list.
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    )}
                </CredenzaBody>
                <CredenzaFooter>
                    <CredenzaClose render={<Button variant="outline" />} data-attr="access-detail-dialog-done">
                        Done
                    </CredenzaClose>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
