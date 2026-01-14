import { ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { ChatMessage } from '../../types'

export interface MessageProps {
    message: ChatMessage
    isCustomer: boolean
}

export function Message({ message, isCustomer }: MessageProps): JSX.Element {
    const profileType = message.authorType === 'AI' ? 'bot' : 'person'

    return (
        <div className={`flex ${isCustomer ? 'mr-10' : 'flex-row-reverse ml-10'} mb-4`}>
            <div className="flex gap-2">
                <div className="flex flex-col min-w-0 items-start">
                    <div className="flex items-center justify-between w-full gap-2 mb-1">
                        <ProfilePicture
                            size="sm"
                            user={message.createdBy}
                            name={message.authorName}
                            type={profileType}
                            showName={true}
                        />
                        <span className="text-xs text-muted-alt">
                            <TZLabel time={message.createdAt} />
                        </span>
                    </div>
                    <div className="max-w-full min-w-80">
                        <div className="border py-2 px-3 rounded-lg bg-surface-primary">
                            <LemonMarkdown className="text-sm">{message.content}</LemonMarkdown>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
