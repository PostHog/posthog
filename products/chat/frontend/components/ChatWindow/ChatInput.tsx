import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { chatListLogic } from '../../scenes/chatListLogic'

export function ChatInput(): JSX.Element {
    const { message } = useValues(chatListLogic)
    const { sendMessage, setMessage } = useActions(chatListLogic)

    return (
        <div className="border-t rounded-b border-gray-200 p-4 absolute bottom-0 left-0 right-0 bg-white">
            <div className="flex gap-2">
                <LemonInput
                    type="text"
                    className="flex-1"
                    placeholder="Type a message…"
                    value={message}
                    onChange={(e) => setMessage(e)}
                    onPressEnter={() => sendMessage(message)}
                />
                <LemonButton onClick={() => sendMessage(message)}>Send</LemonButton>
            </div>
        </div>
    )
}
