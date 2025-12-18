import { TZLabel } from 'lib/components/TZLabel'

import type { CommentType } from '~/types'

export interface MessageProps {
    message: CommentType
    isCustomer: boolean
    displayName: string
}

export function Message({ message, isCustomer, displayName }: MessageProps): JSX.Element {
    return (
        <div className={`flex ${isCustomer ? 'mr-10' : 'flex-row-reverse ml-10'}`}>
            <div className="flex flex-col min-w-0 items-start">
                <div className="text-xs text-muted mb-1 px-1">{displayName}</div>
                <div className="max-w-full">
                    <div className="border py-2 px-3 rounded-lg bg-surface-primary">
                        <p className="text-sm p-0 m-0">{message.content}</p>
                    </div>
                </div>
                <div className="text-xs text-muted-alt mt-1 px-1">
                    {message.created_at && typeof message.created_at === 'string' && (
                        <TZLabel time={message.created_at} />
                    )}
                </div>
            </div>
        </div>
    )
}
