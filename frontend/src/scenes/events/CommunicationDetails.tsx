import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { communicationDetailsLogic } from './CommunicationDetailsLogic'
import { useActions, useValues } from 'kea'
import { IconComment, IconMail } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton/LemonSegmentedButton'

export function CommunicationDetails({ uuid }: { uuid: string }): JSX.Element {
    const { publicReplyEnabled, replyType, noteContent } = useValues(communicationDetailsLogic({ eventUUID: uuid }))
    const { setReplyType, saveNote, setNoteContent } = useActions(communicationDetailsLogic({ eventUUID: uuid }))

    return (
        <>
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
            <LemonTextArea
                id="user-context reply"
                className="definition-popover-edit-form-value"
                autoFocus
                placeholder={publicReplyEnabled ? 'Public reply to the customer via email' : 'Internal note'}
                value={noteContent}
                onChange={(noteContent) => setNoteContent(noteContent)}
                minRows={3}
                maxRows={20}
                data-attr="support-reply-or-internal-note"
            />
            <LemonButton
                icon={publicReplyEnabled ? <IconMail /> : <IconComment />}
                onClick={() => saveNote(noteContent)} // TODO: that should probably just pull the content in the logic side
                tooltip={publicReplyEnabled ? 'Send an email to the customer' : 'Save internal note'}
            >
                {publicReplyEnabled ? 'Send email' : 'Save internal note'}
            </LemonButton>
            {/* TODO: pull all the historical communication, i.e. load events in the logic first */}
        </>
    )
}
