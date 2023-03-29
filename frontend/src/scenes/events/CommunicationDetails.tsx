import { LemonTextArea, LemonTextMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { communicationDetailsLogic } from './CommunicationDetailsLogic'
import { useActions, useValues } from 'kea'
import { IconComment, IconMail } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton/LemonSegmentedButton'

export function CommunicationDetails({ uuid }: { uuid: string }): JSX.Element {
    const { publicReplyEnabled, replyType, noteContent } = useValues(communicationDetailsLogic({ eventUUID: uuid }))
    const { setReplyType, saveNote, setNoteContent } = useActions(communicationDetailsLogic({ eventUUID: uuid }))

    return (
        <div className={'flex flex-col space-y-2 p-4'}>
            <LemonSegmentedButton
                onChange={(value) => setReplyType(value)}
                options={[
                    {
                        icon: <IconComment />,
                        label: 'Internal note',
                        value: 'internal',
                    },
                    {
                        icon: <IconMail />,
                        label: 'Public reply',
                        value: 'public',
                    },
                ]}
                value={replyType}
            />
            {publicReplyEnabled ? (
                <LemonTextArea
                    autoFocus
                    placeholder={publicReplyEnabled ? 'Public reply to the customer via email' : 'Internal note'}
                    value={noteContent}
                    onChange={(noteContent) => setNoteContent(noteContent)}
                    minRows={3}
                    maxRows={20}
                    data-attr={'support-reply-email-text'}
                />
            ) : (
                <LemonTextMarkdown
                    value={noteContent}
                    onChange={(noteContent) => setNoteContent(noteContent)}
                    data-attr={"'support-reply-internal-note-text'"}
                />
            )}
            <div className="flex flex-row justify-end">
                <LemonButton
                    status="primary"
                    type={'primary'}
                    icon={publicReplyEnabled ? <IconMail /> : <IconComment />}
                    onClick={() => saveNote(noteContent)} // TODO: that should probably just pull the content in the logic side
                    tooltip={publicReplyEnabled ? 'Send an email to the customer' : 'Save internal note'}
                    fullWidth={false}
                    disabledReason={noteContent ? undefined : 'Please enter a note'}
                >
                    {publicReplyEnabled ? 'Send email' : 'Save internal note'}
                </LemonButton>
            </div>
            {/* TODO: pull all the historical communication, i.e. load events in the logic first */}
        </div>
    )
}
