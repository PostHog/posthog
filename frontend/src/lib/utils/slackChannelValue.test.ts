import {
    getSlackChannelDisplayLabelFromTargetValueSegment,
    getSlackChannelIdFromTargetValue,
    parseCommaSeparatedSlackTargetDisplayLabels,
    parseSlackTargetForAlertPayload,
} from './slackChannelValue'

describe('slackChannelValue', () => {
    it('getSlackChannelIdFromTargetValue returns id before first pipe', () => {
        expect(getSlackChannelIdFromTargetValue('C123|#general')).toBe('C123')
        expect(getSlackChannelIdFromTargetValue(' C123 |#general')).toBe('C123')
        expect(getSlackChannelIdFromTargetValue('C123')).toBe('C123')
    })

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

    it('parseSlackTargetForAlertPayload returns id and name without hash', () => {
        expect(parseSlackTargetForAlertPayload('C123|#general')).toEqual({
            channelId: 'C123',
            channelName: 'general',
        })
        expect(parseSlackTargetForAlertPayload('C123')).toEqual({ channelId: 'C123', channelName: 'C123' })
    })
})
