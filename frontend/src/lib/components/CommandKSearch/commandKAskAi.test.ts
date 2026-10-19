import { askAiQuestionFor } from './commandKAskAi'
import { FilterOptions, QueryChip, resolveQuery } from './commandKQuery'

const OPTIONS: FilterOptions = {
    is: [
        { value: 'dashboard', label: 'Dashboard' },
        { value: 'insight', label: 'Insight' },
    ],
    createdBy: [
        { value: 'me', label: 'Me' },
        { value: 'mel@example.com', label: 'Mel Ortiz' },
    ],
    in: [],
    name: [],
}

const chip = (key: QueryChip['key'], value: string): QueryChip => ({ key, value, label: value, negated: false })

describe('askAiQuestionFor', () => {
    test.each([
        ['no filters', 'how many signups', [], 'how many signups'],
        ['a type and no text', '', [chip('is', 'dashboard')], null],
        ['a type and text', 'is:insight revenue', [], 'Find insights called "revenue"'],
        ['a creator and text', 'createdBy:me revenue', [], 'Find objects created by me called "revenue"'],
        [
            'several filters and text',
            'is:dashboard -createdBy:mel@example.com revenue',
            [],
            'Find dashboards not created by Mel Ortiz called "revenue"',
        ],
    ])('asks with %s', (_, text, chips, question) => {
        expect(askAiQuestionFor(text, resolveQuery(text, chips, OPTIONS))).toBe(question)
    })
})
