import type { PersonRow } from './peopleQueries'

export function personLabel(row: Pick<PersonRow, 'name' | 'email' | 'distinctId'>): string {
    return row.name ?? row.email ?? row.distinctId
}
