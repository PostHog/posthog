import { buildQueryForColumnClick } from './sql-utils'

describe('buildQueryForColumnClick', () => {
    it('renders dotted table names as qualified identifiers instead of quoting the full path', () => {
        expect(buildQueryForColumnClick(null, 'this.is.sparta', 'SPARTA')).toBe(
            'SELECT SPARTA FROM this.is.sparta LIMIT 100'
        )
    })

    it('toggles columns against dotted table names without rewriting the table path', () => {
        const firstQuery = buildQueryForColumnClick(null, 'this.is.sparta', 'SPARTA')
        expect(firstQuery).toBe('SELECT SPARTA FROM this.is.sparta LIMIT 100')

        const secondQuery = buildQueryForColumnClick(firstQuery, 'this.is.sparta', 'SPARTA')
        expect(secondQuery).toBe('SELECT * FROM this.is.sparta LIMIT 100')

        const thirdQuery = buildQueryForColumnClick(secondQuery, 'this.is.sparta', 'SPARTA')
        expect(thirdQuery).toBe('SELECT SPARTA FROM this.is.sparta LIMIT 100')
    })
})
