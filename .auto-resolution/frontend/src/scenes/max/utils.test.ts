import { checkSuggestionRequiresUserInput, formatSuggestion, stripSuggestionPlaceholders } from './utils'

describe('max/utils', () => {
    describe('checkSuggestionRequiresUserInput()', () => {
        it('returns true for suggestions with angle brackets', () => {
            expect(checkSuggestionRequiresUserInput('Show me <metric> over time')).toBe(true)
            expect(checkSuggestionRequiresUserInput('Compare <event1> vs <event2>')).toBe(true)
            expect(checkSuggestionRequiresUserInput('Filter by <property>')).toBe(true)
        })

        it('returns true for suggestions with ellipsis', () => {
            expect(checkSuggestionRequiresUserInput('Show me trends for…')).toBe(true)
            expect(checkSuggestionRequiresUserInput('Create a funnel…')).toBe(true)
        })

        it('returns true for suggestions with mixed placeholders', () => {
            expect(checkSuggestionRequiresUserInput('Show <metric> trends for…')).toBe(true)
            expect(checkSuggestionRequiresUserInput('Compare <event> over…')).toBe(true)
        })

        it('returns false for suggestions without placeholders', () => {
            expect(checkSuggestionRequiresUserInput('Show me page views')).toBe(false)
            expect(checkSuggestionRequiresUserInput('Create a simple funnel')).toBe(false)
            expect(checkSuggestionRequiresUserInput('Display user retention')).toBe(false)
        })

        it('handles empty and edge cases', () => {
            expect(checkSuggestionRequiresUserInput('')).toBe(false)
            expect(checkSuggestionRequiresUserInput('No special characters')).toBe(false)
            expect(checkSuggestionRequiresUserInput('Just some text')).toBe(false)
        })
    })

    describe('stripSuggestionPlaceholders()', () => {
        it('removes angle bracket placeholders', () => {
            expect(stripSuggestionPlaceholders('Show me <metric> over time')).toBe('Show me  over time ')
            expect(stripSuggestionPlaceholders('Filter by <property>')).toBe('Filter by ')
        })

        it('handles empty string', () => {
            expect(stripSuggestionPlaceholders('')).toBe(' ')
        })
    })

    describe('formatSuggestion()', () => {
        it('removes angle brackets but keeps content', () => {
            expect(formatSuggestion('Show me <metric> over time')).toBe('Show me metric over time')
            expect(formatSuggestion('Compare <event1> vs <event2>')).toBe('Compare event1 vs event2')
            expect(formatSuggestion('Filter by <property>')).toBe('Filter by property')
        })

        it('preserves ellipsis at the end', () => {
            expect(formatSuggestion('Show me trends for…')).toBe('Show me trends for…')
            expect(formatSuggestion('Create a funnel…')).toBe('Create a funnel…')
        })

        it('handles mixed placeholders', () => {
            expect(formatSuggestion('Show <metric> trends for…')).toBe('Show metric trends for…')
            expect(formatSuggestion('Compare <event> over…')).toBe('Compare event over…')
        })

        it('handles suggestions without placeholders', () => {
            expect(formatSuggestion('Show me page views')).toBe('Show me page views')
            expect(formatSuggestion('Create a simple funnel')).toBe('Create a simple funnel')
        })

        it('trims whitespace', () => {
            expect(formatSuggestion('  Show me data  ')).toBe('Show me data')
            expect(formatSuggestion('  Show <metric>  ')).toBe('Show metric')
            expect(formatSuggestion('  Show data…  ')).toBe('Show data…')
        })

        it('handles empty string', () => {
            expect(formatSuggestion('')).toBe('')
        })
    })
})
