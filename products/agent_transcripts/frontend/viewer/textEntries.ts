import { TranscriptEntry } from './transcriptEntries'

const USER_SPEAKERS = new Set(['user', 'human', 'me', 'you', 'you said'])
const SPEAKERS =
    'you said|user|human|me|you|assistant|ai|agent|claude|chatgpt said|chatgpt|cursor|codex|gemini|copilot|model'

// Speaker lines, as chat exports and copied conversations write them: `## User`, `**Assistant:** <text>`,
// `_**Agent (model)**_` (Cursor), `Human: <text>`, `ChatGPT said:`. Each label must be the whole heading,
// the whole bold run or a line prefix with a colon, so a heading such as "## AI setup" is not a new turn.
const SPEAKER_LINES = [
    new RegExp(`^#{1,6}\\s+(${SPEAKERS})(?:\\s*\\([^)]*\\))?\\s*:?\\s*()$`, 'i'),
    new RegExp(`^_?\\*\\*(${SPEAKERS})(?:\\s*\\([^)]*\\))?:?\\*\\*_?:?\\s*(.*)$`, 'i'),
    new RegExp(`^(${SPEAKERS}):\\s*(.*)$`, 'i'),
]
const SEPARATOR_LINE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/

/** Entries from a Markdown or plain text conversation. Without speaker lines, the whole file is one message. */
export function textEntries(text: string): TranscriptEntry[] {
    const turns: { speaker: string; lines: string[]; sequence: number }[] = []

    text.split('\n').forEach((line, index) => {
        const match = SPEAKER_LINES.map((pattern) => pattern.exec(line)).find(Boolean)
        if (match) {
            turns.push({
                speaker: match[1].toLowerCase(),
                lines: match[2] ? [match[2]] : [],
                sequence: index + 1,
            })
        } else if (turns.length) {
            turns[turns.length - 1].lines.push(line)
        }
    })

    if (turns.length === 0) {
        return text.trim() ? [{ id: 'text-0', sequence: 1, kind: 'message', title: '', text: text.trim() }] : []
    }

    return turns.flatMap((turn, index): TranscriptEntry[] => {
        const lines = [...turn.lines]
        while (lines.length && (SEPARATOR_LINE.test(lines[lines.length - 1]) || !lines[lines.length - 1].trim())) {
            lines.pop()
        }
        const body = lines.join('\n').trim()
        return body
            ? [
                  {
                      id: `text-${index}`,
                      sequence: turn.sequence,
                      kind: USER_SPEAKERS.has(turn.speaker) ? 'user' : 'message',
                      title: '',
                      text: body,
                  },
              ]
            : []
    })
}
