import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { IconWarning } from 'lib/lemon-ui/icons'
import React from 'react'
import { userLogic } from 'scenes/userLogic'

export const ChatAvatar = ({ role }: { role: 'system' | 'assistant' | 'user' }): JSX.Element => {
    const { user } = useValues(userLogic)
    return role === 'user' ? (
        <ProfilePicture name={user?.first_name} email={user?.email} size="md" />
    ) : (
        <div>
            <div className="h-8 w-8 rounded-full bg-orange">
                {/* <StaticImage
                    placeholder="none"
                    loading="eager"
                    alt="Chat hog avatar"
                    src="./images/chat-hog-circle.png"
                    width={32}
                /> */}
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

export interface ChatMessage {
    role: 'system' | 'assistant' | 'user'
    content?: string
    loading?: boolean
    onClickRating?: (rating: 'good' | 'bad') => void
    responseTo?: 'text' | 'rating'
    ratingValue?: 'good' | 'bad'
}

export const ChatMessage = ({ role, content, loading }: ChatMessage): JSX.Element => {
    // TODO: import onclickrating and ratingvalue above, had to remove to commit
    // const [rating, setRating] = React.useState<'good' | 'bad' | null>(ratingValue || null)
    // const thumbClasses = `w-4 h-4 fill-gray-accent-light-hover hover:fill-gray-accent-dark-hover transition-colors`
    return (
        <div className="flex gap-x-2 items-end mb-4">
            {role === 'assistant' && <ChatAvatar role={'assistant'} />}
            {content && (
                <>
                    <div className={`bg-${role === 'assistant' ? 'mid' : 'side'} rounded p-4 flex-grow`}>
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
                                <LemonButton icon={<IconWarning />} size="small" status="danger">
                                    Report
                                </LemonButton>
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
