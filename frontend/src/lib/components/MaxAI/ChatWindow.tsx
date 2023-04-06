import React, { useEffect, useRef } from 'react'
import { ChatMessage } from './ChatMessage'
import './MaxAI.scss'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { IconClose } from 'lib/lemon-ui/icons'

export const ChatWindow = ({
    setIsChatActive,
}: {
    setIsChatActive: (isChatActive: boolean) => void | undefined
}): JSX.Element => {
    const [messages, setMessages] = React.useState<ChatMessage[]>()
    const divRef = useRef<HTMLDivElement>(null)
    const [maxResponseLoading, setMaxResponseLoading] = React.useState<boolean>(false)

    useEffect(() => {
        // Scroll to the bottom of the div on mount and whenever its content changes
        if (divRef.current) {
            divRef.current.scrollTop = divRef?.current?.scrollHeight
        }
    }, [divRef.current?.innerHTML])

    const defaultMessage: ChatMessage[] = [
        {
            role: 'assistant',
            content: "Hi there! I'm Max, your friendly AI support assistant. How can I help you today?",
        },
    ]

    const getMessagesFromStorage = (): void => {
        const messagesInStorage = localStorage.getItem('max-ai-messages')
        if (messagesInStorage) {
            const messagesInStorageJSON = JSON.parse(messagesInStorage)
            if (
                messagesInStorageJSON &&
                messagesInStorageJSON.messages.length > 1 &&
                messagesInStorageJSON.expiration > Date.now()
            ) {
                setMessages(messagesInStorageJSON.messages)
            } else {
                setMessages(defaultMessage)
            }
        } else {
            setMessages(defaultMessage)
        }
    }

    const handleCloseClick = (): void => {
        setIsChatActive(false)
    }

    const handleSubmit = (inputContent: string): void => {
        messages &&
            setMessages([
                ...messages,
                {
                    role: 'user',
                    content: inputContent,
                },
            ])
    }

    useEffect(() => {
        const getResponse = async (): Promise<void> => {
            await fetch('https://max.posthog.cc/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(messages),
            })
                .then((res) => res.json())
                .then((res) => {
                    setMaxResponseLoading(false)
                    // add the response to the messages
                    messages &&
                        setMessages([
                            ...messages,
                            {
                                role: 'assistant',
                                content: res,
                            },
                        ])
                })
        }
        const lastMessage = messages?.[messages.length - 1]
        if (
            // the last message was from the user
            lastMessage?.role === 'user' ||
            // or the last message was from the assistant and was a bad rating
            (lastMessage?.role === 'assistant' &&
                lastMessage?.responseTo === 'rating' &&
                lastMessage.ratingValue === 'bad')
        ) {
            setMaxResponseLoading(true)
            getResponse()
        }
        // save the messages to local storage with a key and expiration date for 1 day
        if (messages?.length && messages.length > 1) {
            const expirationDate = new Date()
            expirationDate.setDate(expirationDate.getDate() + 1) // Expires in 1 day
            localStorage.setItem('max-ai-messages', JSON.stringify({ messages, expiration: expirationDate.getTime() }))
        }
    }, [messages])

    useEffect(() => {
        getMessagesFromStorage()
    }, [])

    const handleOnClickRating = (rating: 'good' | 'bad'): void => {
        messages && rating === 'bad'
            ? setMessages([
                  ...messages,
                  {
                      role: 'assistant',
                      content: `Whoops, sorry my response wasn't what you were looking for. I will pass this feedback on to the team and will attempt to re-generate a better response for you.\n\nYou can also send an email to hey@posthog.com to get in touch with a human.`,
                      responseTo: 'rating',
                      ratingValue: 'bad',
                  },
              ])
            : messages &&
              rating === 'good' &&
              setMessages([
                  ...messages,
                  {
                      role: 'assistant',
                      content: `Happy to help! If you have any other questions just let me know.`,
                      responseTo: 'rating',
                      ratingValue: 'good',
                  },
              ])
    }

    return (
        <div className="bg-white rounded-md shadow-lg h-full w-full flex flex-col overflow-hidden">
            <div className="flex rounded-t w-full bg-danger-light justify-between items-center p-4 z-20">
                <div>
                    <h3 className="font-bold text-base text-white m-0">Max AI</h3>
                    <p className="ml-0 text-xs opacity-80 text-white mb-0">PostHog's AI support assistant</p>
                </div>
                <LemonButton
                    icon={<IconClose className="text-white opacity-80" />}
                    onClick={handleCloseClick}
                    status="stealth"
                />
            </div>
            <div className="h-8 mr-3 bg-gradient-to-b from-white to-transparent z-10" />
            <div className="-mt-8 overflow-y-scroll overflow-x-hidden flex-grow flex flex-col" ref={divRef}>
                <div className="pt-8 pb-2 px-4 flex-grow flex flex-col justify-end">
                    {messages?.map((message, index) => (
                        <ChatMessage
                            key={`message-${index}`}
                            role={message.role}
                            content={message.content}
                            onClickRating={handleOnClickRating}
                        />
                    ))}
                    {maxResponseLoading && <ChatMessage role="assistant" loading />}
                </div>
            </div>
            <div className="h-8 -mt-6 mr-3 bg-gradient-to-t from-white to-transparent" />
            <div className="bg-white z-20">
                <LemonInput onPressEnter={handleSubmit} />
            </div>
        </div>
    )
}
