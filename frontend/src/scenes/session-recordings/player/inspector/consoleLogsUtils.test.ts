import { parseEntry } from 'scenes/session-recordings/player/inspector/consoleLogsUtils'

describe('parseEntry()', () => {
    it('empty entries', () => {
        ;['', null, undefined, '   ', '\n', '\t\t', '\t\r\n'].forEach((entry) => {
            expect(parseEntry(entry as unknown as string)).toEqual({
                type: 'string',
                parsed: null,
                rawString: '',
                size: 0,
            })
        })
    })
    it('object or array strings', () => {
        expect(parseEntry('[{"key1": "a","key2":"b"},{"key1": "a","key2":"b"}]')).toEqual({
            type: 'array',
            parsed: [
                { key1: 'a', key2: 'b' },
                { key1: 'a', key2: 'b' },
            ],
            rawString: '[{"key1": "a","key2":"b"},{"key1": "a","key2":"b"}]',
            size: 2,
        })
        expect(parseEntry('{"key1": "a","key2":"b"}')).toEqual({
            type: 'object',
            parsed: { key1: 'a', key2: 'b' },
            rawString: '{"key1": "a","key2":"b"}',
            size: 2,
        })
        expect(
            parseEntry(
                `{"status":0,"message":"TypeError: Failed to fetch\\n    at Object.getRaw (http://localhost:8234/static/chunk-6MCQJ7Y6.js:208552:24)\\n    End of stack for Error object"}`
            )
        ).toMatchSnapshot()
    })
    it('strings containing urls', () => {
        const inputs = [
            'rowRenderer (https://example.com/path/to/file.js:123:456)',
            'ENTRY Object.createElementWithValidation [as createElement] (https://example.com/path/to/file.js:123:456)',
            'ENTRY Object.createElementWithValidation [as createElement] (https://example.com/path/to/file.js)',
            ':1223:12',
            'https://example.com/path/to/file.js:123:456',
            'https://example.com/path/to/file.js:123:456 End of object',
            'https://example.com/path/to/file.js:123:456 https://example.com/path/to/file.js:123:456 https://example.com/path/to/file.js:123:456',
        ]
        inputs.forEach((entry) => {
            const result = parseEntry(entry)
            expect(result).toMatchSnapshot()
            // Flanking double quotes should be removed
            expect(parseEntry(`"${entry}"`)).toEqual(result)
        })
    })
    it('miscellaneous', () => {
        const inputs = [
            'record',
            '\n    in Fragment\n    in Grid5 (created by List6)\n    in List6 (created by AutoSizer2)\n    in div (created by AutoSizer2)\n    in AutoSizer2 (created by PlayerList)',
            '\\n    in Fragment',
            'Warning: Each child in a list should have a unique "key" prop.%s%s See https://fb.me/react-warning-keys for more information.%s',
        ]
        inputs.forEach((entry) => {
            expect(parseEntry(entry)).toMatchSnapshot()
        })
    })
})
