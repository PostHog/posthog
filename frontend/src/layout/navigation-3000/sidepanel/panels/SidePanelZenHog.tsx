import { LemonFileInput, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { LemonButton, LemonDivider, LemonTextArea, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useAsyncActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconWithCount, IconZendesk } from 'lib/lemon-ui/icons'
import React, { Fragment, ReactElement, ReactNode, useEffect, useRef, useState } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { SidePanelTab } from '~/types'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { SIDE_PANEL_TABS } from '../SidePanel'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { SupportFormBlock } from './SidePanelSupport'
import { ZendeskTicket, ZendeskTicketEvent, zenHogLogic } from './sidePanelZenHogLogic'

export const SidePanelZenHogIcon = (props: { className?: string }): JSX.Element => {
    // TODO Dylan load these from the sidePanelZenHogLogic
    const zenHogTicketCount = 4
    // const { zenHogTicketCount, zenHogTicketPage } = useValues(sidePanelStatusLogic)

    const title =
        zenHogTicketCount >= 0
            ? `Click here to see your ${zenHogTicketCount} open support tickets`
            : 'No open support tickets'

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithCount count={zenHogTicketCount} showZero={false}>
                    <IconZendesk />
                </IconWithCount>
            </span>
        </Tooltip>
    )
}

//TODO Dylan this is yoinked from the Help sidebar so it's a bit jank.  Consider improving.
const Section = ({ title, children }: { title: string; children: ReactNode }): ReactElement => {
    return (
        <section className="mb-6">
            <h3>{title}</h3>
            {children}
        </section>
    )
}

export const SidePanelZenHog = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { openEmailForm, closeEmailForm } = useActions(supportLogic)
    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { title } = useValues(theLogic)
    const { isEmailFormOpen } = useValues(supportLogic)

    return (
        <>
            <SidePanelPaneHeader title={isEmailFormOpen ? title : SIDE_PANEL_TABS[SidePanelTab.ZenHog].label} />
            <div className="flex flex-col overflow-hidden">
                <div className="flex-1 p-4 overflow-y-auto space-y-4">
                    {isEmailFormOpen ? (
                        <SupportFormBlock onCancel={() => closeEmailForm()} />
                    ) : (
                        <>
                            <Section title="My Zendesk Tickets">
                                <ZendeskTicketPanel />
                            </Section>
                            <Section title="Create a New Zendesk Ticket">
                                <p>Need additional help? Start a new support session with us!</p>
                                <LemonButton
                                    type="primary"
                                    fullWidth
                                    center
                                    onClick={() => openEmailForm()}
                                    targetBlank
                                    className="mt-2"
                                >
                                    Create new ticket
                                </LemonButton>
                            </Section>
                        </>
                    )}
                </div>
            </div>
        </>
    )
}

export function ZendeskTicketPanel(): JSX.Element {
    const { openZendeskTickets } = useValues(zenHogLogic)
    const { loadZendeskTickets } = useActions(zenHogLogic)

    useEffect(() => {
        loadZendeskTickets()
    }, [])

    return (
        <div className="flex flex-col relative min-h-24">
            {openZendeskTickets.length > 0 ? (
                openZendeskTickets.map((ticket, index) => (
                    <Fragment key={ticket.id}>
                        {index > 0 && <LemonDivider className="my-4" />}
                        <ZendeskTicketDisplay ticket={ticket} />
                    </Fragment>
                ))
            ) : (
                <SpinnerOverlay />
            )}
            {openZendeskTickets.length === 0 && (
                <i className="text-center">
                    No open support tickets.
                    <br />
                    Check back later!
                </i>
            )}
        </div>
    )
}

function ZendeskTicketDisplay({ ticket }: { ticket: ZendeskTicket }): JSX.Element {
    const { submitZendeskTicketReply } = useAsyncActions(zenHogLogic)
    const [replyMessage, setReplyMessage] = useState('')
    const [expandTicket, setExpandTicket] = useState(false)
    const [events, setEvents] = useState(ticket.events)
    const [filesToUpload, setFilesToUpload] = useState<File[]>([])
    const [uploading, setUploading] = useState(false)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const dropRef = useRef<HTMLDivElement>(null)
    const uploadedFilesRef = useRef<{ fileName: string; url: string }[]>([])

    const handleTicketToggle = (): void => {
        setExpandTicket(!expandTicket)
        if (!expandTicket) {
            setEvents(ticket.events)
        }
    }

    const handleSubmitReply = async (): Promise<void> => {
        let fileLinks = ''
        if (filesToUpload.length > 0) {
            setUploading(true)
            const uploadedFiles = await Promise.all(
                filesToUpload.map(async (file) => {
                    // TODO DYLAN Simulate file upload logic, replace with actual upload function
                    const url = await uploadFile(file)
                    return { fileName: file.name, url }
                })
            )
            setUploading(false)
            uploadedFilesRef.current = uploadedFiles // Store uploaded files for display
            fileLinks = uploadedFiles.map((file) => `\n\nAttachment "${file.fileName}": ${file.url}`).join('')
        }

        await submitZendeskTicketReply(ticket.id, replyMessage + fileLinks)

        const newEvent: ZendeskTicketEvent = {
            id: events.length + 1,
            created_at: new Date(),
            updated_at: new Date(),
            message: replyMessage + fileLinks,
            kind: 'user' as any, // TODO DYLAN make these types, "any" is for pussies and democrats
        }
        setEvents((prevEvents) => [...prevEvents, newEvent])
        setReplyMessage('')
        setFilesToUpload([])
        uploadedFilesRef.current = []
    }

    // TODO DYLAN this is a dummy upload function, replace with actual implementation
    const uploadFile = async (file: File): Promise<string> => {
        return new Promise((resolve) => {
            setTimeout(() => resolve(`https://example.com/${file.name}`), 1000)
        })
    }

    // Determine SLA based on urgency
    const urgencyToSLA = {
        low: 'Response within 48 hours',
        medium: 'Response within 24 hours',
        high: 'Response within 4 hours',
    }

    const lastEvent = events[events.length - 1] // TODO DYLAN consider safe tail instead
    const buttonText = lastEvent.kind === 'user' ? 'Add additional information' : 'Reply'
    const buttonClass = lastEvent.kind === 'user' ? 'w-48' : 'w-24'
    const placeHolderText = lastEvent.kind === 'user' ? 'Add additional information...' : 'Type your reply...'
    const slaMessage = urgencyToSLA[ticket.urgency]

    return (
        <div>
            <div className="cursor-pointer" onClick={handleTicketToggle}>
                <h4 className="font-semibold mb-0">
                    {ticket.subject} <LemonTag className="ml-2">{slaMessage}</LemonTag>
                </h4>
                <p className="text-gray-600">{ticket.description}</p>
            </div>
            {expandTicket && (
                <>
                    {events.map((event) => (
                        <div key={event.id} className="pl-4">
                            <p>
                                <b>{event.kind.replace('_', ' ').toUpperCase()}:</b>{' '}
                                {event.message.split('\n\n').map((msg, idx) => (
                                    <span key={idx}>
                                        {msg.includes('Attachment') ? (
                                            // eslint-disable-next-line react/forbid-elements
                                            <a href={msg.split(': ')[1]} target="_blank" rel="noopener noreferrer">
                                                {msg.split('"')[1]}
                                            </a>
                                        ) : (
                                            msg
                                        )}
                                        <br />
                                    </span>
                                ))}
                            </p>
                        </div>
                    ))}
                    <div className="flex flex-col gap-2 mt-2">
                        {objectStorageAvailable && !!user && (
                            <LemonFileInput
                                accept="image/*"
                                multiple={false}
                                alternativeDropTargetRef={dropRef}
                                onChange={setFilesToUpload}
                                loading={uploading}
                                value={filesToUpload}
                            />
                        )}
                        <div ref={dropRef} className="flex flex-col gap-2">
                            <LemonTextArea
                                placeholder={placeHolderText}
                                value={replyMessage}
                                onChange={setReplyMessage}
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    setReplyMessage('')
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    void handleSubmitReply().then(() => {
                                        setReplyMessage('')
                                    })
                                }}
                                className={buttonClass}
                                center
                            >
                                {buttonText}
                            </LemonButton>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
