import { newestByName } from './todayNewestByName'

describe('newestByName', () => {
    it('keeps the newest rows, lists them by name, and does not swap rows with the same name', () => {
        const name = (item: { name: string; id: string }): string => item.name
        const id = (item: { name: string; id: string }): string => item.id
        const row = (name: string, id: string = name): { name: string; id: string } => ({ name, id })
        const newestFirst = ['Pricing', 'apps', 'Zebra', 'Alerts'].map((label) => row(label))

        expect(newestByName(newestFirst, name, id, 3).map(name)).toEqual(['apps', 'Pricing', 'Zebra'])

        const twins = [row('Untitled', 'a'), row('Untitled', 'b')]
        expect(newestByName(twins, name, id, 2)).toEqual(newestByName([...twins].reverse(), name, id, 2))
    })

    it('puts numbered names in number order', () => {
        const rows = ['Ticket #10', 'Ticket #9'].map((label) => ({ name: label, id: label }))
        expect(
            newestByName(
                rows,
                (row) => row.name,
                (row) => row.id,
                2
            ).map((row) => row.name)
        ).toEqual(['Ticket #9', 'Ticket #10'])
    })
})
