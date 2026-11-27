import { blocksText, JsonRecord, record, string, TranscriptEntry, toolKind, toolText } from './transcriptEntries'

/** The ChatGPT data export (`conversations.json`): a message tree per conversation, read along the current branch. */
function chatGptEntries(conversation: JsonRecord, prefix: string): TranscriptEntry[] {
    const mapping = record(conversation.mapping)
    const branch: JsonRecord[] = []
    const seen = new Set<string>()
    let nodeId = string(conversation.current_node)
    while (nodeId && !seen.has(nodeId)) {
        seen.add(nodeId)
        const node = record(mapping[nodeId])
        branch.unshift(record(node.message))
        nodeId = string(node.parent)
    }

    return branch.flatMap((message, index): TranscriptEntry[] => {
        const role = string(record(message.author).role)
        const content = record(message.content)
        const id = `${prefix}-${index}`
        const sequence = index + 1
        if (!role || role === 'system' || record(message.metadata).is_visually_hidden_from_conversation) {
            return []
        }

        if (content.content_type === 'thoughts') {
            const text = (Array.isArray(content.thoughts) ? content.thoughts : [])
                .map((thought) => string(record(thought).content))
                .join('\n\n')
            return text ? [{ id, sequence, kind: 'thinking', title: '', text }] : []
        }
        if (content.content_type === 'code') {
            const name = string(message.recipient) || 'code'
            return [{ id, sequence, kind: toolKind(name), title: name, text: string(content.text), status: 'passed' }]
        }

        const text = blocksText(content.parts) || string(content.text)
        if (!text) {
            return []
        }
        if (role === 'tool') {
            const name = string(record(message.author).name) || 'tool'
            return [{ id, sequence, kind: toolKind(name), title: name, text: '', output: text, status: 'passed' }]
        }
        return [{ id, sequence, kind: role === 'user' ? 'user' : 'message', title: '', text }]
    })
}

/** The Claude app data export (`conversations.json`): each message has a sender and content blocks. */
function claudeAppEntries(conversation: JsonRecord, prefix: string): TranscriptEntry[] {
    const messages = Array.isArray(conversation.chat_messages) ? conversation.chat_messages : []
    const entries: TranscriptEntry[] = []

    messages.forEach((raw, index) => {
        const message = record(raw)
        const sequence = index + 1
        const blocks = Array.isArray(message.content) ? message.content : [{ type: 'text', text: message.text }]
        const kind = message.sender === 'human' ? 'user' : 'message'

        blocks.forEach((rawBlock, blockIndex) => {
            const block = record(rawBlock)
            const id = `${prefix}-${index}-${blockIndex}`
            if (block.type === 'text' && string(block.text)) {
                entries.push({ id, sequence, kind, title: '', text: string(block.text) })
            } else if (block.type === 'thinking' && string(block.thinking)) {
                entries.push({ id, sequence, kind: 'thinking', title: '', text: string(block.thinking) })
            } else if (block.type === 'tool_use') {
                const name = string(block.name) || 'tool'
                entries.push({ id, sequence, kind: toolKind(name), title: name, text: toolText(block.input) })
            } else if (block.type === 'tool_result') {
                // The export has no call IDs, so a result belongs to the latest call that has none yet.
                const call = [...entries].reverse().find((entry) => entry.title && entry.output === undefined)
                const output = blocksText(block.content)
                const status = block.is_error ? 'failed' : 'passed'
                if (call) {
                    call.output = output
                    call.status = status
                } else {
                    const name = string(block.name) || 'tool'
                    entries.push({ id, sequence, kind: toolKind(name), title: name, text: '', output, status })
                }
            }
        })
    })

    return entries.map((entry) => (entry.title && !entry.status ? { ...entry, status: 'passed' } : entry))
}

const isChatGptConversation = (value: JsonRecord): boolean => 'mapping' in value && 'current_node' in value
const isClaudeAppConversation = (value: JsonRecord): boolean => Array.isArray(value.chat_messages)

/** Entries from a ChatGPT or Claude app export, or null when the JSON is neither. */
export function conversationExportEntries(json: unknown): TranscriptEntry[] | null {
    const conversations = (Array.isArray(json) ? json : [json]).map(record)
    const parse = conversations.every(isChatGptConversation)
        ? chatGptEntries
        : conversations.every(isClaudeAppConversation)
          ? claudeAppEntries
          : null
    if (!parse || conversations.length === 0) {
        return null
    }

    return conversations.flatMap((conversation, index) => {
        const title = string(conversation.title) || string(conversation.name)
        const entries = parse(conversation, `conversation-${index}`)
        // An export can hold many conversations. A heading row marks where each one starts.
        return conversations.length > 1
            ? [
                  {
                      id: `conversation-${index}`,
                      sequence: 0,
                      kind: 'system' as const,
                      title: 'Conversation',
                      text: title || `${index + 1}`,
                  },
                  ...entries,
              ]
            : entries
    })
}
