import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { NodeKind, type AccountsTableRow } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { productUsageGridLogic } from './productUsageGridLogic'
import { buildProductUsageHogQLQuery } from './productUsageQueries'
import { ProductUsageQueryEditor } from './ProductUsageQueryEditor'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
let mockEditorProps: any
jest.mock('lib/monaco/CodeEditor', () => ({
    CodeEditor: (props: any) => {
        mockEditorProps = props
        return <div data-attr="book-code-editor" />
    },
}))
const account: AccountsTableRow = {
    id: 'account-1',
    name: 'Example',
    externalId: "org'quote",
    accountFields: {},
    relationships: {},
    customProperties: {},
    customPropertyHistory: {},
}
describe('ProductUsageQueryEditor metadata bindings', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })
    afterEach(cleanup)
    it('validates the same plural account placeholders and filters used by Run', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        const sql = 'SELECT {account_ids}, {account_external_ids}'
        logic.actions.setQueryDraft(sql)
        logic.actions.finishLoad({
            accounts: { kind: NodeKind.AccountsTableQuery, results: [account], limit: 200, offset: 0, hasMore: false },
            matrix: null,
            hogql: null,
            source: { kind: 'product_usage' },
        })
        render(<ProductUsageQueryEditor />)
        await screen.findByTestId('book-code-editor')
        const execution = buildProductUsageHogQLQuery(
            sql,
            [account],
            logic.values.controls.dateRange,
            logic.values.customerAnalyticsConfig?.account_group_type_index
        )
        expect(mockEditorProps.globals).toEqual(execution.values)
        expect(mockEditorProps.sourceQuery.filters).toEqual(execution.filters)
        logic.unmount()
    })
    it('can edit filters before accounts load and still rejects an unconfigured Run', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.setQueryDraft('SELECT * FROM events WHERE {filters}')
        render(<ProductUsageQueryEditor />)
        await screen.findByTestId('book-code-editor')
        expect(mockEditorProps.globals).toEqual({ account_ids: [], account_external_ids: [] })
        expect(() => buildProductUsageHogQLQuery(logic.values.queryDraft, [], {}, null)).toThrow(
            'Choose an account group type'
        )
        logic.unmount()
    })
})
describe('ProductUsageQueryEditor source kind', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_PRODUCT_USAGE]: true })
    })
    afterEach(cleanup)
    it('lets a saved product usage source switch to a custom HogQL query', async () => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.setSource({ kind: 'product_usage' })
        logic.actions.openEditor('product_usage')
        render(<ProductUsageQueryEditor />)
        expect(screen.queryByTestId('book-code-editor')).toBeNull()
        fireEvent.click(screen.getByText('Custom HogQL'))
        await screen.findByTestId('book-code-editor')
        expect(logic.values.queryDraft).toContain('FROM events')
        expect(logic.values.source).toEqual({ kind: 'product_usage' })
        logic.unmount()
    })
})
