import { getThumbIcon } from './SurveyView'

describe('getThumbIcon', () => {
    it.each([
        ['string "1"', '1', true],
        ['number 1', 1, true],
        ['string "2"', '2', false],
        ['number 2', 2, false],
    ])('returns correct icon for %s', (_label, value, expectThumbsUp) => {
        const result = getThumbIcon(value)
        expect(result).not.toBeNull()
        expect(result!.props.className).toContain(expectThumbsUp ? 'text-brand-blue' : 'text-warning')
    })
})
