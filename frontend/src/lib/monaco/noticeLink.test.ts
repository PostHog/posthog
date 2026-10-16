import type { Monaco } from '@monaco-editor/react'

import { noticeLink } from './noticeLink'

describe('noticeLink', () => {
    const monaco = { Uri: { parse: (value: string) => ({ parsed: value }) } } as unknown as Pick<Monaco, 'Uri'>

    it('links an https url with the surrounding whitespace removed', () => {
        expect(noticeLink('  https://example.com/announcement  ', monaco)).toEqual({
            value: 'Learn more',
            target: { parsed: 'https://example.com/announcement' },
        })
    })

    it.each([
        ['a command url', 'command:editor.action.deleteLines'],
        ['a javascript url', 'javascript:alert(1)'],
        ['an http url', 'http://example.com/announcement'],
        ['no url', undefined],
    ])('adds no link for %s', (_name: string, url: string | undefined) => {
        expect(noticeLink(url, monaco)).toBeUndefined()
    })

    it('adds no link when Monaco rejects an https url', () => {
        const rejectingMonaco = {
            Uri: {
                parse: () => {
                    throw new Error('[UriError]')
                },
            },
        } as unknown as Pick<Monaco, 'Uri'>

        expect(noticeLink('https:////x', rejectingMonaco)).toBeUndefined()
    })
})
