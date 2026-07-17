import { CATEGORY_ORDER, DATA_MANAGEMENT_PANEL_ORDER } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { APPS_CATEGORY_ORDER, appsItemName, sortItems } from './navAppsTabLogic'

describe('navAppsTabLogic', () => {
    // The desktop Apps tab merges the real app's two separate panels — the products/tools panel
    // (CATEGORY_ORDER) and the data management panel (DATA_MANAGEMENT_PANEL_ORDER) — into one list.
    // If the merged order stops mirroring those two, the desktop menu shows groups in a different
    // order than the web app. That drift is the regression this locks down.
    it('lists tools categories first (in the products-panel order), then data (in the data-panel order)', () => {
        const dataOnly = Object.entries(DATA_MANAGEMENT_PANEL_ORDER)
            .sort(([, a], [, b]) => a - b)
            .map(([category]) => category)
            .filter((category) => !CATEGORY_ORDER.includes(category))

        expect(APPS_CATEGORY_ORDER.slice(0, CATEGORY_ORDER.length)).toEqual(CATEGORY_ORDER)
        expect(APPS_CATEGORY_ORDER.slice(CATEGORY_ORDER.length)).toEqual(dataOnly)
    })

    // Within a section the real app honors visualOrder before name; a pure alphabetical sort would
    // flip pairs like Persons (visualOrder 10) / Cohorts (visualOrder 20).
    it('orders items within a section by visualOrder, then by name', () => {
        const items = [
            { path: 'Cohorts', visualOrder: 20 },
            { path: 'Persons', visualOrder: 10 },
            { path: 'Banana' },
            { path: 'Apple' },
        ] as FileSystemImport[]

        expect(sortItems(items).map(appsItemName)).toEqual(['Persons', 'Cohorts', 'Apple', 'Banana'])
    })
})
