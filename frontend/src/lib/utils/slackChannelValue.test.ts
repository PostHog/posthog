import {
    getSlackChannelDisplayLabelFromTargetValueSegment,
    parseCommaSeparatedSlackTargetDisplayLabels,
} from './slackChannelValue'

describe('slackChannelValue', () => {
    it('getSlackChannelDisplayLabelFromTargetValueSegment returns hash label or full value', () => {
        expect(getSlackChannelDisplayLabelFromTargetValueSegment('C123|#general')).toBe('#general')
        expect(getSlackChannelDisplayLabelFromTargetValueSegment('C123')).toBe('C123')
        expect(getSlackChannelDisplayLabelFromTargetValueSegment('')).toBeNull()
        expect(getSlackChannelDisplayLabelFromTargetValueSegment('   ')).toBeNull()
    })

    it('parseCommaSeparatedSlackTargetDisplayLabels splits comma list and drops empties', () => {
        expect(parseCommaSeparatedSlackTargetDisplayLabels('C1|#a, C2|#b')).toEqual(['#a', '#b'])
        expect(parseCommaSeparatedSlackTargetDisplayLabels('C1|#a, , C2|#b')).toEqual(['#a', '#b'])
    })
})
