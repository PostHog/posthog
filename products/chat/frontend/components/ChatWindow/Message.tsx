import { TZLabel } from 'lib/components/TZLabel'

import { ChatMessage } from '../../scenes/chatListLogic'

export function Message({ msg }: { msg: ChatMessage }): JSX.Element {
    return (
        <div key={msg.id} className={`flex ${msg.is_assistant ? 'justify-end' : 'justify-start'}`}>
            <div>
                <div className="px-4 py-2 rounded-lg max-w-xs break-words bg-gray-200">{msg.content}</div>
                <TZLabel
                    className="overflow-hidden text-ellipsis text-xs text-secondary shrink-0"
                    time={msg.created_at}
                    placement="right"
                />
            </div>
        </div>
    )
}
