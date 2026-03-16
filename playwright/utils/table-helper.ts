import { Locator } from '@playwright/test'

async function getText(locator: Locator): Promise<string> {
    return ((await locator.textContent()) ?? '').trim()
}

async function cellsToArray(locator: Locator): Promise<string[]> {
    const count = await locator.count()
    const result: string[] = []

    for (let i = 0; i < count; i++) {
        result.push(await getText(locator.nth(i)))
    }

    return result
}

export class TableRow {
    constructor(
        private readonly helper: TableHelper,
        private readonly tr: Locator
    ) {}

    async column(nameOrIndex: string | number): Promise<string> {
        const index = typeof nameOrIndex === 'string' ? await this.helper.resolveColumnIndex(nameOrIndex) : nameOrIndex
        return getText(this.tr.locator('td').nth(index))
    }

    async values(): Promise<Record<string, string>> {
        const hdrs = await this.helper.headers()
        const cells = await cellsToArray(this.tr.locator('td'))
        return Object.fromEntries(hdrs.map((h, i) => [h, cells[i] ?? '']))
    }
}

export class TableHelper {
    private readonly bodyRows: Locator

    constructor(private readonly table: Locator) {
        this.bodyRows = table.locator('tbody tr')
    }

    async headers(): Promise<string[]> {
        return cellsToArray(this.table.locator('thead th'))
    }

    async column(nameOrIndex: string | number): Promise<string[]> {
        const index = typeof nameOrIndex === 'string' ? await this.resolveColumnIndex(nameOrIndex) : nameOrIndex
        const count = await this.bodyRows.count()
        const values: string[] = []

        for (let i = 0; i < count; i++) {
            values.push(await getText(this.bodyRows.nth(i).locator('td').nth(index)))
        }

        return values
    }

    row(indexOrFilter: number | string | RegExp): TableRow {
        const tr =
            typeof indexOrFilter === 'number'
                ? this.bodyRows.nth(indexOrFilter)
                : this.bodyRows.filter({ hasText: indexOrFilter })

        return new TableRow(this, tr)
    }

    async rows(): Promise<Record<string, string>[]> {
        const count = await this.bodyRows.count()
        const result: Record<string, string>[] = []

        for (let i = 0; i < count; i++) {
            result.push(await this.row(i).values())
        }

        return result
    }

    async resolveColumnIndex(name: string): Promise<number> {
        const hdrs = await this.headers()
        const index = hdrs.findIndex((h) => h.toLowerCase().includes(name.toLowerCase()))
        if (index === -1) {
            throw new Error(`Column "${name}" not found. Available headers: ${hdrs.join(', ')}`)
        }
        return index
    }
}
