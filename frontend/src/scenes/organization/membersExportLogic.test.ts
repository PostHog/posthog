import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_USER_UUID } from 'lib/api.mock'

import { buildOrganizationMembersCsv } from './membersExportLogic'

describe('buildOrganizationMembersCsv', () => {
    it('prefixes cells starting with a formula character so spreadsheets read them as text', () => {
        const csv = buildOrganizationMembersCsv([
            {
                ...MOCK_DEFAULT_ORGANIZATION_MEMBER,
                user: { ...MOCK_DEFAULT_BASIC_USER, first_name: '=1+1', email: '+1@example.com' },
            },
        ])

        expect(csv.split('\r\n')[1]).toEqual(
            `"'=1+1","'+1@example.com",Owner,No,No,No,2020-09-24T15:05:26.758796Z,2020-09-24T15:05:26.758796Z,${MOCK_USER_UUID}`
        )
    })
})
