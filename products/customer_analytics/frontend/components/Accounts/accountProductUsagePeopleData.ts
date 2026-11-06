import type { BookActivityMatrixResult, BookActivityPerson } from '~/queries/schema/schema-general'

export function getLatestProductUsageColumn(result: BookActivityMatrixResult): string {
    return result.columns.reduce((latest, column) => (column.key > latest ? column.key : latest), '')
}

export function getAccountProductUsagePeopleCell(
    result: BookActivityMatrixResult,
    accountId: string,
    people: BookActivityPerson[],
    productKey: string,
    columnKey: string
): { people: BookActivityPerson[]; total: number } {
    return {
        people: people
            .filter((person) => person.row === accountId && person.series === productKey && person.column === columnKey)
            .sort((a, b) => a.rank - b.rank),
        total:
            result.data.find(
                (cell) => cell.row === accountId && cell.series === productKey && cell.column === columnKey
            )?.users ?? 0,
    }
}
