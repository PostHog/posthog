import { useActions, useValues } from 'kea'

import { IconCursorClick, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'

import { fieldNotesLogic } from './fieldNotesLogic'

export function FieldNotesToolbarMenu(): JSX.Element {
    const { fieldNotes, fieldNotesLoading, isFieldNoting, deletingId } = useValues(fieldNotesLogic)
    const { startFieldNote, stopFieldNote, deleteFieldNote } = useActions(fieldNotesLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header className="pt-2">
                <span className="block px-2 pt-3">Field notes</span>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="px-2 pb-2 space-y-3">
                    <p className="text-xs text-muted mt-0 mb-4">
                        Point at any element and leave a note. Your AI coding agent can read these over PostHog's MCP
                        and can turn them into changes — then mark them resolved.
                    </p>
                    <p className="text-xs text-muted mt-0 mb-4">
                        Ask your agent for your <strong>project's Field notes</strong> to get the list.
                    </p>
                    <LemonButton
                        type="primary"
                        fullWidth
                        center
                        icon={<IconCursorClick />}
                        onClick={() => (isFieldNoting ? stopFieldNote() : startFieldNote())}
                    >
                        {isFieldNoting ? 'Cancel — click an element…' : 'Add a field note'}
                    </LemonButton>

                    <div className="space-y-1">
                        <div className="text-xs font-medium text-muted uppercase">Pending</div>
                        {fieldNotesLoading ? (
                            <div className="flex justify-center py-4">
                                <Spinner />
                            </div>
                        ) : fieldNotes.length > 0 ? (
                            fieldNotes.map((note) => (
                                <div
                                    key={note.id}
                                    className="rounded border border-border p-2 text-sm bg-bg-light flex items-start gap-2"
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="truncate">{note.comment}</div>
                                        <div className="text-muted text-xs truncate">{note.selector}</div>
                                    </div>
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconTrash />}
                                        tooltip="Delete field note"
                                        loading={deletingId === note.id}
                                        disabledReason={deletingId === note.id ? 'Deleting…' : undefined}
                                        onClick={() => deleteFieldNote(note.id)}
                                    />
                                </div>
                            ))
                        ) : (
                            <p className="text-muted text-sm text-center py-2">No pending field notes</p>
                        )}
                    </div>
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
