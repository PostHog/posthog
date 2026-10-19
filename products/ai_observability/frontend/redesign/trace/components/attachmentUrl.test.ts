import { classifyAttachmentUrl } from './attachmentUrl'

describe('classifyAttachmentUrl', () => {
    it.each([
        ['data:image/png;base64,iVBORw0KGgo=', 'data'],
        ['blob:https://app.example.com/x', 'sameOrigin'],
        ['/api/projects/1/ai_blob/abc', 'sameOrigin'],
        ['https://media.example.com/a.mp3', 'external'],
        ['javascript:alert(1)', null],
        ['vbscript:x', null],
        ['JAVASCRIPT:alert(1)', null],
        ['//evil.example.com/x', null],
        ['/\\evil.example.com/x', null],
        ['', null],
        [null, null],
    ] as const)('classifies %p as %p', (url, expected) => {
        expect(classifyAttachmentUrl(url)).toBe(expected)
    })
})
