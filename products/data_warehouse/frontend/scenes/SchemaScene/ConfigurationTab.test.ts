import { excludedColumnNames } from './ConfigurationTab'

describe('excludedColumnNames', () => {
    const available = [{ name: 'id' }, { name: 'name' }, { name: 'email' }, { name: 'created_at' }]

    it('returns nothing when the selection syncs all columns', () => {
        expect(excludedColumnNames(null, available, new Set())).toEqual([])
    })

    it('lists columns the pinned selection drops', () => {
        expect(excludedColumnNames(['id', 'name'], available, new Set())).toEqual(['email', 'created_at'])
    })

    it('surfaces a newly-added upstream column the selection has never seen', () => {
        const withNewColumn = [...available, { name: 'phone' }]
        expect(excludedColumnNames(['id', 'name', 'email', 'created_at'], withNewColumn, new Set())).toEqual(['phone'])
    })

    it('never reports always-retained columns as excluded', () => {
        expect(excludedColumnNames(['name'], available, new Set(['id', 'created_at']))).toEqual(['email'])
    })

    it('treats an empty selection with nothing retained as sync-all', () => {
        // The backend projects an empty effective selection to SELECT *, so no column is dropped.
        expect(excludedColumnNames([], available, new Set())).toEqual([])
    })

    it('still drops columns when an empty selection keeps only a retained column', () => {
        // With a primary key retained the backend syncs just that column, so the rest are excluded.
        expect(excludedColumnNames([], available, new Set(['id']))).toEqual(['name', 'email', 'created_at'])
    })
})
