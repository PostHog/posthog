import { conversationExportEntries } from './conversationExportEntries'
import { eventEntries } from './eventEntries'
import { textEntries } from './textEntries'
import { parseJson, TranscriptEntry } from './transcriptEntries'

/**
 * Readable entries from an uploaded transcript. The format comes from the file's content, not from the
 * agent the member picked, because people pick "Other" or the wrong agent and the upload still has a shape.
 */
export function parseTranscript(text: string): TranscriptEntry[] {
    const json = parseJson(text)
    if (json !== undefined) {
        const exported = conversationExportEntries(json)
        if (exported) {
            return exported
        }
        if (Array.isArray(json)) {
            return eventEntries(json)
        }
    }

    const lines = text.split('\n').filter((line) => line.trim())
    const events = lines.map(parseJson).filter((event) => typeof event === 'object' && event !== null)
    // A JSONL file has one JSON object per line. A few broken lines, such as a truncated last line, still count.
    if (lines.length && events.length >= lines.length * 0.9) {
        const entries = eventEntries(events)
        if (entries.length) {
            return entries
        }
    }

    return textEntries(text)
}
