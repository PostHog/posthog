import { buildFieldNotesPrompt } from './fieldNotePrompt'
import type { FieldNote } from './fieldNotesLogic'

const NOTE: FieldNote = {
    id: '0197c0a2-1f1e-7a4a-9b8f-2f9c3f1b4d10',
    comment: 'This button should say "Save changes"',
    field_note_status: 'pending',
    resolution: null,
    url: 'https://example.com/settings',
    host: 'example.com',
    pathname: '/settings',
    selector: 'div.settings-panel > button.save',
    element_text: 'Save',
    screenshot_url: 'https://example.com/uploaded_media/1',
    created_at: '2026-08-31T10:12:00Z',
}

describe('buildFieldNotesPrompt', () => {
    it('carries what the agent needs to find the element and close the note', () => {
        const prompt = buildFieldNotesPrompt([NOTE])

        expect(prompt).toContain(NOTE.comment)
        expect(prompt).toContain(NOTE.selector)
        expect(prompt).toContain(NOTE.url)
        expect(prompt).toContain(NOTE.element_text)
        expect(prompt).toContain(NOTE.screenshot_url)
        expect(prompt).toContain(NOTE.id)
        expect(prompt).toContain('field-notes-partial-update')
    })

    it('leaves out the lines a note has no value for', () => {
        const prompt = buildFieldNotesPrompt([{ ...NOTE, element_text: null, screenshot_url: null }])

        expect(prompt).not.toContain('Element text:')
        expect(prompt).not.toContain('Screenshot:')
    })

    it('numbers every note when several go out together', () => {
        const prompt = buildFieldNotesPrompt([NOTE, { ...NOTE, id: 'second-note-id' }])

        expect(prompt).toContain('Field note 1')
        expect(prompt).toContain('Field note 2')
        expect(prompt).toContain('second-note-id')
    })
})
