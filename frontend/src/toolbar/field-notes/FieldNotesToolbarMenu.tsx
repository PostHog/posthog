import { useActions, useValues } from 'kea'

import { IconChevronDown, IconCopy, IconCursorClick, IconSparkles, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'

import { CLIPBOARD_AGENT_KEY, FIELD_NOTE_AGENTS, fieldNoteAgentName } from './fieldNoteAgents'
import { fieldNotesLogic } from './fieldNotesLogic'

export function FieldNotesToolbarMenu(): JSX.Element {
    const { fieldNotes, fieldNotesLoading, isFieldNoting, deletingId, agentKey } = useValues(fieldNotesLogic)
    const { startFieldNote, stopFieldNote, deleteFieldNote, sendNotesToAgent, setAgentKey } =
        useActions(fieldNotesLogic)

    const agentName = fieldNoteAgentName(agentKey)
    const toClipboard = agentKey === CLIPBOARD_AGENT_KEY
    const noteCount = fieldNotes.length
    const noteLabel = noteCount === 1 ? '1 note' : `${noteCount} notes`
    const sendAllLabel = toClipboard ? `Copy prompt for ${noteLabel}` : `Send ${noteLabel} to ${agentName}`

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header className="pt-2">
                <span className="block px-2 pt-3">Field notes</span>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="px-2 pb-2 space-y-3">
                    <p className="text-xs text-muted mt-0 mb-4">
                        Point at any element and leave a note. Send the notes to your coding agent, or ask the agent for
                        your <strong>project's field notes</strong> over PostHog's MCP.
                    </p>
                    <LemonButton
                        type="primary"
                        fullWidth
                        center
                        icon={<IconCursorClick />}
                        onClick={() => (isFieldNoting ? stopFieldNote() : startFieldNote())}
                        data-attr="field-notes-add"
                    >
                        {isFieldNoting ? 'Cancel, click an element…' : 'Add a field note'}
                    </LemonButton>

                    <div className="flex gap-1">
                        <LemonButton
                            type="secondary"
                            className="flex-1 min-w-0"
                            center
                            icon={toClipboard ? <IconCopy /> : <IconSparkles />}
                            onClick={() => sendNotesToAgent(fieldNotes.map((note) => note.id))}
                            disabledReason={
                                fieldNotesLoading
                                    ? 'Loading your field notes'
                                    : noteCount === 0
                                      ? 'Add a field note first'
                                      : undefined
                            }
                            data-attr="field-notes-send-all"
                        >
                            {sendAllLabel}
                        </LemonButton>
                        <LemonMenu
                            items={FIELD_NOTE_AGENTS.map((agent) => ({
                                label: agent.name,
                                active: agent.key === agentKey,
                                onClick: () => setAgentKey(agent.key),
                            }))}
                        >
                            <LemonButton
                                type="secondary"
                                className="shrink-0"
                                icon={<IconChevronDown />}
                                tooltip="Pick where field notes go"
                                data-attr="field-notes-pick-agent"
                            />
                        </LemonMenu>
                    </div>

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
                                        icon={toClipboard ? <IconCopy /> : <IconSparkles />}
                                        tooltip={
                                            toClipboard ? 'Copy prompt for this note' : `Send this note to ${agentName}`
                                        }
                                        onClick={() => sendNotesToAgent([note.id])}
                                        data-attr="field-notes-send-one"
                                    />
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconTrash />}
                                        tooltip="Delete field note"
                                        loading={deletingId === note.id}
                                        disabledReason={deletingId === note.id ? 'Deleting…' : undefined}
                                        onClick={() => deleteFieldNote(note.id)}
                                        data-attr="field-notes-delete"
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
