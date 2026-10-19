import { encodeTraceIdSegment } from './traceIdSegment'

describe('encodeTraceIdSegment', () => {
    it.each([
        ['abc', 'YWJj'],
        ['run.42', 'cnVuLjQy'],
        ['a b#c', 'YSBiI2M'],
        ['a/b', 'YS9i'],
        ['.', 'Lg'],
        ['é/ü', 'w6kvw7w'],
    ])('encodes %s as %s', (traceId, segment) => {
        expect(encodeTraceIdSegment(traceId)).toEqual(segment)
    })
})
