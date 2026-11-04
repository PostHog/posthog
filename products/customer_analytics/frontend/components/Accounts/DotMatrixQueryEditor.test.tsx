import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import { DotMatrixColumnMapping } from './DotMatrixColumnMapping'
import { DotMatrixQueryEditor } from './DotMatrixQueryEditor'
import { createMatrixHogQLQuery } from './dotMatrixTileQuery'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))

let mockEditorImports = 0
let mockEditorProps: any
jest.mock('lib/monaco/CodeEditor', () => {
    mockEditorImports += 1
    if (mockEditorImports === 1) {
        throw new TypeError('Failed to fetch dynamically imported module: CodeEditor.js')
    }
    return {
        CodeEditor: (props: any) => {
            mockEditorProps = props
            return <div data-attr="matrix-code-editor" />
        },
    }
})

describe('DotMatrixQueryEditor', () => {
    beforeEach(() => {
        initKeaTests()
    })
    afterEach(cleanup)

    it('recovers when the editor chunk fails to download once', async () => {
        const logic = accountDotMatrixTileLogic({
            instanceId: 'chunk',
            accountId: 'account-1',
            initialConfig: { source: null },
        })
        logic.mount()
        render(<DotMatrixQueryEditor logic={logic} />)

        expect(await screen.findByTestId('matrix-code-editor', {}, { timeout: 3000 })).toBeTruthy()
        expect(mockEditorImports).toBe(2)
        logic.unmount()
    })

    it('validates the same account placeholders and filters used by Run', async () => {
        const logic = accountDotMatrixTileLogic({
            instanceId: 'bindings',
            accountId: 'account-1',
            externalId: "org'quote",
            initialConfig: { source: null },
        })
        logic.mount()
        const sql = 'SELECT {week_start_day}, {account_id}, {account_external_id}'
        logic.actions.setQueryDraft(sql)
        render(<DotMatrixQueryEditor logic={logic} />)
        await screen.findByTestId('matrix-code-editor')
        const execution = createMatrixHogQLQuery(sql, {
            accountId: 'account-1',
            externalId: "org'quote",
            weeks: logic.values.config.weeks,
            groupTypeIndex: logic.values.customerAnalyticsConfig.account_group_type_index,
            weekStartDay: logic.values.weekStartDay,
        })
        expect(mockEditorProps.globals).toEqual(execution.values)
        expect(mockEditorProps.sourceQuery.filters).toEqual(execution.filters)
        logic.unmount()
    })

    it('can edit filters before an account is linked without weakening Run validation', async () => {
        const logic = accountDotMatrixTileLogic({
            instanceId: 'unlinked',
            accountId: 'account-1',
            initialConfig: { source: null },
        })
        logic.mount()
        logic.actions.setQueryDraft('SELECT * FROM events WHERE {filters}')
        render(<DotMatrixQueryEditor logic={logic} />)
        await screen.findByTestId('matrix-code-editor')
        expect(mockEditorProps.sourceQuery.filters).not.toBeUndefined()
        expect(() => createMatrixHogQLQuery(logic.values.queryDraft, { accountId: 'account-1', weeks: 8 })).toThrow(
            'Link this account'
        )
        logic.unmount()
    })

    it('offers an optional user column in the mapping', () => {
        render(
            <DotMatrixColumnMapping
                columns={['r', 'c', 'who']}
                mapping={{ row: 'r', column: 'c' }}
                onChange={jest.fn()}
            />
        )
        expect(screen.getByTestId('dot-matrix-mapping-user').textContent).toContain('No user column')
        expect(screen.getByTestId('dot-matrix-mapping-rowLabel').textContent).toContain('Use row key')
    })
})
