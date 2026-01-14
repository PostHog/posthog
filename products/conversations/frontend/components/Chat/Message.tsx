import { TZLabel } from 'lib/components/TZLabel'

import type { ChatMessage } from '../../types'

export interface MessageProps {
    message: ChatMessage
    isCustomer: boolean
}

export function Message({ message, isCustomer }: MessageProps): JSX.Element {
    return (
        <div className={`flex ${isCustomer ? 'mr-10' : 'flex-row-reverse ml-10'}`}>
            <div className="flex flex-col min-w-0 items-start">
                <div className="text-xs text-muted mb-1 px-1">{message.authorName}</div>
                <div className="max-w-full">
                    <div className="border py-2 px-3 rounded-lg bg-surface-primary">
                        <p className="text-sm p-0 m-0 whitespace-pre-wrap">{message.content}</p>
                    </div>
                </div>
                <div className="text-xs text-muted-alt mt-1 px-1">
                    <TZLabel time={message.createdAt} />
                </div>
            </div>
        </div>
    )
}
