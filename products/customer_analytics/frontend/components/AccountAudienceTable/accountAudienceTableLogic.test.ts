import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { AccountsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    accountRelationshipDefinitionsList,
    customPropertyDefinitionsList,
} from 'products/customer_analytics/frontend/generated/api'

import { ACCOUNTS_TAGS_COLUMN, accountsColumnConfigLogic } from '../Accounts/accountsColumnConfigLogic'
import { accountAudienceTableLogic, createAccountAudienceQuery } from './accountAudienceTableLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountRelationshipDefinitionsList: jest.fn(),
    customPropertyDefinitionsList: jest.fn(),
}))

const AUDIENCE_QUERY: AccountsQuery = {
    kind: NodeKind.AccountsQuery,
    filterExpression: "accounts.external_id != ''",
}

const NO_TABLE_FILTERS = { searchQuery: '', tagsFilter: [], assignmentStatus: 'all' as const, assignedToFilter: [] }

describe('accountAudienceTableLogic', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            current_team: MOCK_DEFAULT_TEAM,
            current_user: MOCK_DEFAULT_USER,
        } as any
        initKeaTests()
        jest.mocked(accountRelationshipDefinitionsList).mockResolvedValue({ count: 0, results: [] } as any)
        jest.mocked(customPropertyDefinitionsList).mockResolvedValue({ count: 0, results: [] } as any)
    })

    it.each([
        ['no table filters', NO_TABLE_FILTERS, {}],
        [
            'search and tags',
            { ...NO_TABLE_FILTERS, searchQuery: ' acme ', tagsFilter: ['vip'] },
            { search: 'acme', tagNames: ['vip'] },
        ],
        [
            'unassigned accounts',
            { ...NO_TABLE_FILTERS, assignmentStatus: 'unassigned' as const },
            { allRolesUnassigned: true },
        ],
        ['any assignee', { ...NO_TABLE_FILTERS, assignmentStatus: 'assigned' as const }, { assignedOnly: true }],
        [
            'specific assignees',
            { ...NO_TABLE_FILTERS, assignmentStatus: 'assigned' as const, assignedToFilter: [7] },
            { assignedToUserIds: [7] },
        ],
    ])('keeps the audience predicate and adds %s', (_, filters, expected) => {
        const query = createAccountAudienceQuery(AUDIENCE_QUERY, filters)

        expect(query.filterExpression).toBe(AUDIENCE_QUERY.filterExpression)
        expect({
            search: query.search,
            tagNames: query.tagNames,
            allRolesUnassigned: query.allRolesUnassigned,
            assignedOnly: query.assignedOnly,
            assignedToUserIds: query.assignedToUserIds,
        }).toEqual({
            search: undefined,
            tagNames: undefined,
            allRolesUnassigned: undefined,
            assignedOnly: undefined,
            assignedToUserIds: undefined,
            ...expected,
        })
    })

    it('keeps column changes out of the Accounts page and drops them when the table closes', async () => {
        const props = {
            scope: 'test-audience',
            audienceQuery: AUDIENCE_QUERY,
            source: 'workflow_batch_audience' as const,
        }
        const pageColumns = accountsColumnConfigLogic()
        pageColumns.mount()
        const defaultColumns = pageColumns.values.selectColumns

        const firstOpen = accountAudienceTableLogic(props)
        firstOpen.mount()
        const audienceColumns = accountsColumnConfigLogic({ scope: props.scope })
        await expectLogic(audienceColumns).toFinishAllListeners()
        audienceColumns.actions.unselectColumn(ACCOUNTS_TAGS_COLUMN)

        expect(audienceColumns.values.selectColumns).not.toContain(ACCOUNTS_TAGS_COLUMN)
        expect(audienceColumns.values.canSaveView).toBe(false)
        expect(pageColumns.values.selectColumns).toEqual(defaultColumns)
        expect(pageColumns.values.canSaveView).toBe(true)

        firstOpen.unmount()
        const secondOpen = accountAudienceTableLogic(props)
        secondOpen.mount()
        await expectLogic(accountsColumnConfigLogic({ scope: props.scope })).toFinishAllListeners()

        expect(accountsColumnConfigLogic({ scope: props.scope }).values.selectColumns).toEqual(defaultColumns)

        secondOpen.unmount()
        pageColumns.unmount()
    })
})
