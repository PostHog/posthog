import { useEffect, useRef } from 'react'
import { ChatMessage } from './ChatMessage'
import './MaxAI.scss'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'
import { IconClose } from 'lib/lemon-ui/icons'
import { maxAILogic } from './maxAILogic'
import { Field, Form } from 'kea-forms'
import { useValues } from 'kea'

export const ChatWindow = ({
    setIsChatActive,
}: {
    setIsChatActive: (isChatActive: boolean) => void | undefined
}): JSX.Element => {
    const divRef = useRef<HTMLDivElement>(null)
    const { isMaxResponseLoading, messages, errorSubmittingMessage } = useValues(maxAILogic)

    useEffect(() => {
        // Scroll to the bottom of the div on mount and whenever its content changes
        if (divRef.current) {
            divRef.current.scrollTop = divRef?.current?.scrollHeight
        }
    }, [divRef.current?.innerHTML])

    const handleCloseClick = (): void => {
        setIsChatActive(false)
    }

    // const handleOnClickRating = (rating: 'good' | 'bad'): void => {
    // messages && rating === 'bad'
    //     ? setMessages([
    //           ...messages,
    //           {
    //               role: 'assistant',
    //               content: `Whoops, sorry my response wasn't what you were looking for. I will pass this feedback on to the team and will attempt to re-generate a better response for you.\n\nYou can also send an email to hey@posthog.com to get in touch with a human.`,
    //               responseTo: 'rating',
    //               ratingValue: 'bad',
    //           },
    //       ])
    //     : messages &&
    //       rating === 'good' &&
    //       setMessages([
    //           ...messages,
    //           {
    //               role: 'assistant',
    //               content: `Happy to help! If you have any other questions just let me know.`,
    //               responseTo: 'rating',
    //               ratingValue: 'good',
    //           },
    //       ])
    // }

    return (
        <div className="bg-white rounded-md shadow h-full w-full flex flex-col overflow-hidden">
            <div className="flex rounded-t w-full bg-danger-light justify-between items-center p-4 z-20">
                <div>
                    <div className="flex gap-x-2 items-center">
                        <h3 className="font-bold text-base text-white m-0">Max AI</h3>
                        <div>
                            <LemonTag type="caution">Beta</LemonTag>
                        </div>
                    </div>
                    <p className="ml-0 text-xs opacity-80 text-white mb-0">PostHog's AI support assistant</p>
                </div>
                <LemonButton
                    icon={<IconClose className="text-white opacity-80" />}
                    onClick={handleCloseClick}
                    status="stealth"
                />
            </div>
            <div className="MaxAI--TopScrollBuffer h-8 mr-3 z-10" />
            <div className="-mt-8 overflow-y-scroll overflow-x-hidden grow flex flex-col" ref={divRef}>
                <div className="pt-8 pb-2 px-4 flex flex-col justify-end grow">
                    <p className="mx-6 mb-6 italic text-muted leading-none text-center text-xs">
                        Max AI is in a beta stage and may say some unexpected things. This chat will be recorded so we
                        can review responses and adjust the algorithm accordingly.
                    </p>
                    {messages?.map((message, index) => (
                        <ChatMessage
                            key={`message-${index}`}
                            role={message.role}
                            content={message.content}
                            ratingValue={message.ratingValue}
                            index={index}
                        />
                    ))}
                    {isMaxResponseLoading && <ChatMessage role="assistant" loading />}
                    {errorSubmittingMessage && (
                        <p className="text-center text-xs text-danger-light italic">
                            We seem to be having difficult communicating with Max. Please wait a moment and try again.
                        </p>
                    )}
                </div>
            </div>
            <div className="MaxAI--BottomScrollBuffer h-8 -mt-6 mr-3 bg-gradient-to-t from-white to-transparent" />
            <div className="bg-white z-20 p-4">
                <Form logic={maxAILogic} formKey="sendChatMessage" enableFormOnSubmit className="flex">
                    <div className="grow">
                        <Field name="message">
                            <LemonInput type="text" placeholder="Type your message here" />
                        </Field>
                    </div>
                    <LemonButton htmlType="submit" className="ml-4" type="primary">
                        Submit
                    </LemonButton>
                </Form>
            </div>
        </div>
    )
}
