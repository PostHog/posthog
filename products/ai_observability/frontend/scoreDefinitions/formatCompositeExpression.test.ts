import { formatCompositeExpression } from './formatCompositeExpression'

describe('composite formula preview', () => {
    it.each([
        [
            '(("excellent" in score1) and not ("partial" in score1 or "off_topic" in score1))',
            '(("excellent" in score1)\nand not ("partial" in score1\n  or "off_topic" in score1))',
        ],
        ['"good" if safe and accurate else "bad"', '"good"\nif safe\nand accurate\nelse "bad"'],
        ['(2 * score1 + score2) / 3', '(2 * score1 + score2) / 3'],
        ["\"and (or)\" in score1 and 'if \\'else' in score2", "\"and (or)\" in score1\nand 'if \\'else' in score2"],
        ['"unfinished and or', '"unfinished and or'],
    ])('formats %s without changing values or operators', (expression, expected) => {
        expect(formatCompositeExpression(expression)).toBe(expected)
    })
})
