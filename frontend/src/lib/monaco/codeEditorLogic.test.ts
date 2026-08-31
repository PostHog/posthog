import type { HogQLNotice } from '~/queries/schema/schema-general'

import { type MarkerPlacement, codePointOffsetToUtf16, noticeToMarker } from './codeEditorLogic'

describe('codeEditorLogic', () => {
    describe('codePointOffsetToUtf16', () => {
        const EMOJI_QUERY = "SELECT countIf(event = '🎉') FROM events"

        test.each([
            ['identity without astral characters', 'SELECT 1 FROM events', 20, 20],
            ['start of the text', EMOJI_QUERY, 0, 0],
            ['before the emoji', EMOJI_QUERY, 24, 24],
            ['start of the events reference', EMOJI_QUERY, 33, 34],
            ['end of the query', EMOJI_QUERY, EMOJI_QUERY.length, 40],
        ])('%s', (_name, text, codePointOffset, expected) => {
            expect(codePointOffsetToUtf16(text as string, codePointOffset as number)).toBe(expected)
        })

        it('lands an insertion after the events reference rather than inside it', () => {
            // The parser reports the end of `events` as 39 code points; Monaco holds 40 UTF-16 units.
            const utf16 = codePointOffsetToUtf16(EMOJI_QUERY, 39)

            expect(EMOJI_QUERY.slice(0, utf16)).toBe(EMOJI_QUERY)
            expect(EMOJI_QUERY.slice(0, 39)).not.toBe(EMOJI_QUERY)
        })
    })

    describe('noticeToMarker', () => {
        // The metadata query is the second statement and holds an emoji, so a correct range has to
        // carry the statement offset and the code point to UTF-16 conversion at once.
        const PREVIOUS_STATEMENT = 'select 1;\n'
        const QUERY = "select countIf(event = '🎉') from events"
        const SCRIPT = PREVIOUS_STATEMENT + QUERY

        const placement: MarkerPlacement = {
            query: QUERY,
            markerOffset: PREVIOUS_STATEMENT.length,
            positionAt: (offset: number) => {
                const before = SCRIPT.slice(0, offset)
                return { lineNumber: before.split('\n').length, column: offset - before.lastIndexOf('\n') }
            },
            statementScope: { startLineNumber: 2, startColumn: 1, endLineNumber: 2, endColumn: QUERY.length + 1 },
        }

        // The backend counts code points, so the emoji makes these smaller than the UTF-16 offsets.
        const codePointIndexOf = (token: string): number => Array.from(QUERY.slice(0, QUERY.indexOf(token))).length

        // Line 2 starts where the metadata query does, so a column indexes the query directly.
        const selectedText = (startColumn: number, endColumn: number): string =>
            QUERY.slice(startColumn - 1, endColumn - 1)

        it('points the marker range at the flagged token', () => {
            const notice: HogQLNotice = {
                start: codePointIndexOf('events'),
                end: codePointIndexOf('events') + 'events'.length,
                message: 'Unknown table',
            }

            const marker = noticeToMarker(notice, 8, placement)

            expect(marker.startLineNumber).toBe(2)
            expect(selectedText(marker.startColumn, marker.endColumn)).toBe('events')
        })

        it('points a fix action edit at the token it replaces', () => {
            const notice: HogQLNotice = {
                start: 0,
                end: QUERY.length,
                message: 'This query scans every event',
                fix_action: {
                    title: 'Add a time range',
                    edits: [
                        {
                            start: codePointIndexOf('events'),
                            end: codePointIndexOf('events') + 'events'.length,
                            text: 'events where timestamp > now() - interval 1 day',
                        },
                    ],
                },
            }

            const marker = noticeToMarker(notice, 4, placement)

            const range = marker.hogQLFixAction!.edits[0].range
            expect(selectedText(range.startColumn, range.endColumn)).toBe('events')
        })
    })
})
