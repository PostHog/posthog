import { discoveredSelectOptions } from './discoveredSelectOptions'
import { autoDiscoveredOption } from './quickFilterOptions'

const web = autoDiscoveredOption('web')
const python = autoDiscoveredOption('posthog-python')

describe('discoveredSelectOptions', () => {
    it.each([
        {
            description: 'shows the Any option and the pinned selection without a search',
            search: '',
            discoveredOptions: [web],
            expectedVisible: [null, python.id, web.id],
        },
        {
            description: 'shows only matches while searching, so ArrowDown and Enter pick a match',
            search: 'we',
            discoveredOptions: [web],
            expectedVisible: [web.id],
        },
    ])('$description', ({ search, discoveredOptions, expectedVisible }) => {
        const options = discoveredSelectOptions('Library', discoveredOptions, python.id, search)

        expect(options.filter((option) => !option.hidden).map((option) => option.value)).toEqual(expectedVisible)
        // The selected value stays in the list, hidden or not, so the trigger keeps showing it
        expect(options.map((option) => option.value)).toContain(python.id)
    })
})
