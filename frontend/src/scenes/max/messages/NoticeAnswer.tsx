import { IconInfo } from '@posthog/icons'

import { NoticeMessage } from '~/queries/schema/schema-assistant-messages'

import { MessageTemplate } from './MessageTemplate'

interface NoticeAnswerProps {
    message: NoticeMessage
}

export function NoticeAnswer({ message }: NoticeAnswerProps): JSX.Element {
    return (
        <MessageTemplate type="ai" boxClassName="bg-surface-secondary border-border-light">
            <div className="flex items-center gap-2 text-muted">
                <IconInfo className="text-lg flex-shrink-0" />
                <span className="text-sm italic">{message.content}</span>
            </div>
        </MessageTemplate>
    )
}
