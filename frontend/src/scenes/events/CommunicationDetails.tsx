import { LemonTextArea, LemonTextMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { communicationDetailsLogic, CommunicationResponse } from './CommunicationDetailsLogic'
import { useActions, useValues } from 'kea'
import { IconComment, IconMail } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton/LemonButton'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton/LemonSegmentedButton'
import { useEffect } from 'react'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { TZLabel } from 'lib/components/TZLabel'

function Message({ communication, markdown = false }: { communication: any; markdown?: boolean }): JSX.Element {
    return (
        <div className={'flex flex-col'}>
            <div className={'text-left text-xs text-muted mb-1'}>{communication.from}</div>
            {markdown ? (
                <TextContent text={communication.body_plain} />
            ) : (
                <div className={'p-2 w-full'}>{communication.body_plain}</div>
            )}
            <>
                <TZLabel time={communication.timestamp} className={'text-muted text-xs text-right'} noStyles={true} />
            </>
        </div>
    )
}

function SentMessage({ communication }: { communication: any }): JSX.Element {
    return (
        <div className={'flex flex-row justify-start mr-20'}>
            <div className={'CommunicationMessage border rounded p-2 bg-warning-highlight'}>
                <Message communication={communication} />
            </div>
        </div>
    )
}

function ReceivedMessage({ communication }: { communication: any }): JSX.Element {
    return (
        <div className={'flex flex-row justify-end ml-20'}>
            <div className={'CommunicationMessage border rounded p-2 bg-success-highlight'}>
                <Message communication={communication} />
            </div>
        </div>
    )
}

function InternalNote({ communication }: { communication: any }): JSX.Element {
    return (
        <div className={'flex flex-row justify-center mx-10'}>
            <div className={'CommunicationMessage border rounded p-2 bg-primary-alt-highlight'}>
                <Message communication={communication} markdown={true} />
            </div>
        </div>
    )
}

function MessageHistory({
    loading,
    communications,
}: {
    communications: CommunicationResponse
    loading: boolean
}): JSX.Element {
    return (
        <div className={'flex flex-col space-y-2 p-4'}>
            <h3>Messages (last 7 days)</h3>
            <LemonDivider />
            {loading ? (
                <Spinner />
            ) : communications?.results?.length > 0 ? (
                communications.results.map((communication, index) => {
                    return communication?.event === '$communication_email_sent' ? (
                        <SentMessage key={index} communication={communication} />
                    ) : communication?.event === '$communication_email_received' ||
                      communication?.event === '$bug_report' ? (
                        <ReceivedMessage key={index} communication={communication} />
                    ) : (
                        <InternalNote key={index} communication={communication} />
                    )
                })
            ) : (
                <div className={'text-muted text-center uppercase'}>No messages yet</div>
            )}
        </div>
    )
}

export function CommunicationDetails({ uuid }: { uuid: string }): JSX.Element {
    const { publicReplyEnabled, replyType, noteContent, communications, communicationsLoading } = useValues(
        communicationDetailsLogic({ eventUUID: uuid })
    )
    const { setReplyType, saveNote, setNoteContent, loadCommunications } = useActions(
        communicationDetailsLogic({ eventUUID: uuid })
    )

    useEffect(() => {
        loadCommunications()
    }, [])

    return (
        <div className={'flex flex-col space-y-2 p-4'}>
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
            <LemonDivider />
            <MessageHistory loading={communicationsLoading} communications={communications} />
        </div>
    )
}
