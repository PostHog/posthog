import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { IconWarning } from 'lib/lemon-ui/icons'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import { ChatHogCircle } from '../hedgehogs'
import { ChatMessageType } from '~/types'
import { maxAILogic } from './maxAILogic'

export const ChatAvatar = ({ role }: { role: 'system' | 'assistant' | 'user' }): JSX.Element => {
    const { user } = useValues(userLogic)
    return role === 'user' ? (
        <ProfilePicture name={user?.first_name} email={user?.email} className="h-8 w-8" />
    ) : (
        <div>
            <div className="h-8 w-8 rounded-full bg-danger">
                <ChatHogCircle className="w-full h-full" />
            </div>
        </div>
    )
}

const TypingIndicator = (): JSX.Element => {
    return (
        <div className="typing-indicator">
            <div className="dot" />
            <div className="dot" />
            <div className="dot" />
        </div>
    )
}

export const ChatMessage = ({ role, content, loading, ratingValue, index }: ChatMessageType): JSX.Element => {
    const { sendBadMessageRating } = useActions(maxAILogic)
    return (
        <div className={`flex gap-x-2 items-end mb-4 ${role === 'user' ? 'justify-end ml-16' : 'mr-16'}`}>
            {role === 'assistant' && <ChatAvatar role={'assistant'} />}
            {content && (
                <>
                    <div
                        className={`bg-${
                            role === 'assistant' ? 'bg-3000-light' : 'glass-border-3000-light'
                        } rounded p-4 flex-grow`}
                    >
                        <p className="flex-shrink mb-0 text-sm">
                            {content.split('\n').map((item, idx) => {
                                return (
                                    <React.Fragment key={idx}>
                                        {item}
                                        <br />
                                    </React.Fragment>
                                )
                            })}
                        </p>
                        {role === 'assistant' && (
                            <div className="flex gap-x-2 justify-end mt-1">
                                {/* <button
                                    onClick={() => {
                                        onClickRating && onClickRating('good')
                                        setRating('good')
                                    }}
                                >
                                    <ThumbUp className={`${thumbClasses}${rating === 'good' && ' !fill-green'}`} />
                                </button> */}
                                {/* <button
                                    onClick={() => {
                                        onClickRating && onClickRating('bad')
                                        setRating('bad')
                                    }}
                                >
                                    <ThumbDown className={`${thumbClasses}${rating === 'bad' && ' fill-red'}`} />
                                </button> */}
                                <LemonButton
                                    icon={
                                        <IconWarning className={`w-4 h-4 ${ratingValue === 'bad' && 'text-danger'}`} />
                                    }
                                    size="small"
                                    status="danger"
                                    htmlType="submit"
                                    onClick={() => index && sendBadMessageRating(index)}
                                />
                            </div>
                        )}
                    </div>
                </>
            )}
            {loading && <TypingIndicator />}
            {role === 'user' && <ChatAvatar role={'user'} />}
        </div>
    )
}
