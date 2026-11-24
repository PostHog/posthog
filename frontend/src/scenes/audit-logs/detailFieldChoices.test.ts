import { ScopeFields } from './advancedActivityLogsLogic'
import { DetailFieldSearch, getDetailFieldChoices, getVisibleDetailFieldChoices } from './detailFieldChoices'

describe('detailFieldChoices', () => {
    const scope = (...names: string[]): ScopeFields => ({ fields: names.map((name) => ({ name, types: ['string'] })) })
    const search = (overrides: Partial<DetailFieldSearch> = {}): DetailFieldSearch => ({
        searchTerm: '',
        excludedFieldPaths: [],
        ...overrides,
    })
    const manyChoices = getDetailFieldChoices({
        Insight: scope(...Array.from({ length: 5000 }, (_, i) => `changes[].after.key_${i}`)),
    })

    it('orders shallow paths before deep ones and merges a field that several scopes share', () => {
        const choices = getDetailFieldChoices({
            Insight: scope('changes[].after.filters.alpha', 'name'),
            FeatureFlag: scope('name', 'changes[].field', 'Zeta', 'alpha'),
        })

        expect(choices).toEqual([
            { fieldName: 'alpha', leafName: 'alpha', scopes: ['FeatureFlag'] },
            { fieldName: 'name', leafName: 'name', scopes: ['Insight', 'FeatureFlag'] },
            { fieldName: 'Zeta', leafName: 'Zeta', scopes: ['FeatureFlag'] },
            { fieldName: 'changes[].field', leafName: 'field', scopes: ['FeatureFlag'] },
            { fieldName: 'changes[].after.filters.alpha', leafName: 'alpha', scopes: ['Insight'] },
        ])
    })

    it('leaves out a field that another filter uses, in every scope that has it', () => {
        const choices = getDetailFieldChoices({ Insight: scope('name', 'short_id'), FeatureFlag: scope('name') })

        const { visible } = getVisibleDetailFieldChoices(choices, search({ excludedFieldPaths: ['Insight::name'] }))

        expect(visible.map((choice) => choice.value)).toEqual(['Insight::short_id'])
    })

    it.each([
        { searchTerm: '', expectedVisible: 100, expectedMatchCount: 5000 },
        { searchTerm: 'KEY_49', expectedVisible: 100, expectedMatchCount: 111 },
        { searchTerm: 'insight key_4999', expectedVisible: 1, expectedMatchCount: 1 },
        { searchTerm: 'no_such_field', expectedVisible: 0, expectedMatchCount: 0 },
    ])(
        'shows $expectedVisible of $expectedMatchCount matches for "$searchTerm"',
        ({ searchTerm, expectedVisible, expectedMatchCount }) => {
            const { visible, matchCount } = getVisibleDetailFieldChoices(manyChoices, search({ searchTerm }))

            expect(visible).toHaveLength(expectedVisible)
            expect(matchCount).toBe(expectedMatchCount)
        }
    )

    it.each([
        { searchTerm: '', expectedFirst: 'Insight::changes[].after.key_4999', expectedInVisible: true },
        { searchTerm: 'key_1', expectedFirst: 'Insight::changes[].after.key_1', expectedInVisible: false },
    ])(
        'keeps a selected field outside the first 100 available for "$searchTerm"',
        ({ searchTerm, expectedFirst, expectedInVisible }) => {
            const selectedFieldPath = 'Insight::changes[].after.key_4999'

            const { visible, selected } = getVisibleDetailFieldChoices(
                manyChoices,
                search({ searchTerm, selectedFieldPath })
            )

            expect(selected?.value).toBe(selectedFieldPath)
            expect(visible).toHaveLength(100)
            expect(visible[0].value).toBe(expectedFirst)
            expect(visible.some((choice) => choice.isSelected)).toBe(expectedInVisible)
        }
    )

    it('puts the closest field names first', () => {
        const choices = getDetailFieldChoices({
            Insight: scope(
                'name.first',
                'changes[].after.filename',
                'changes[].after.name_template',
                'changes[].after.name',
                'changes[].after.color'
            ),
        })

        const { visible } = getVisibleDetailFieldChoices(choices, search({ searchTerm: 'name' }))

        expect(visible.map((choice) => choice.fieldName)).toEqual([
            'changes[].after.name',
            'changes[].after.name_template',
            'changes[].after.filename',
            'name.first',
        ])
    })
})
