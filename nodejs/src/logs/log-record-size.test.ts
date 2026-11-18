import { logRecordSizeBytes } from './log-record-size'

describe('logRecordSizeBytes', () => {
    it.each([
        [{ body: null, severity_text: null, attributes: null, resource_attributes: null }, 0],
        [{ body: '', severity_text: '', attributes: {}, resource_attributes: {} }, 0],
        [{ body: '😀', severity_text: 'é', attributes: { 漢: '"✓"' }, resource_attributes: { r: 'true' } }, 19],
    ])('counts UTF-8 string and map content for %j', (record, expected) => {
        expect(logRecordSizeBytes(record)).toBe(expected)
    })
})
