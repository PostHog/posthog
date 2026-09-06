import type { FieldNote } from './fieldNotesLogic'

function describeFieldNote(note: FieldNote, index: number): string {
    const lines = [
        `Field note ${index + 1}`,
        `- Asked for: ${note.comment}`,
        `- Page: ${note.url}`,
        `- Element selector: ${note.selector}`,
    ]
    if (note.element_text) {
        lines.push(`- Element text: ${note.element_text}`)
    }
    if (note.screenshot_url) {
        lines.push(`- Screenshot: ${note.screenshot_url}`)
    }
    lines.push(`- Field note id: ${note.id}`)
    return lines.join('\n')
}

/**
 * Turn field notes into a prompt for a coding agent. The agent gets the element identity it
 * needs to find the code, and the MCP tool call that closes the note once the change is made.
 */
export function buildFieldNotesPrompt(notes: FieldNote[]): string {
    const intro =
        notes.length === 1
            ? 'Here is a field note I captured with the PostHog toolbar. It points at one element of my site and says what should change about it.'
            : `Here are ${notes.length} field notes I captured with the PostHog toolbar. Each one points at an element of my site and says what should change about it.`

    return `${intro}

${notes.map(describeFieldNote).join('\n\n')}

For each field note:
1. Find the element in this codebase. The selector and the element text tell you what to look for.
2. Make the change the note asks for.
3. Close the note with PostHog's MCP: call \`field-notes-partial-update\` with the field note id, \`field_note_status\` set to \`resolved\`, and a short \`resolution\` that says what you changed.

Ask me before you make a change that the note leaves open to interpretation.
`
}
