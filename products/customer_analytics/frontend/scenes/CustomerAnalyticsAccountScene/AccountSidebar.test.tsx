import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AccountApi, CustomPropertyDefinitionApi } from '../../generated/api.schemas'
import { AccountSidebar } from './AccountSidebar'
import { accountSidebarPropertiesLogic } from './accountSidebarPropertiesLogic'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    userHasAccess: () => true,
}))

describe('AccountSidebar refresh recovery', () => {
    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
    })

    it('keeps the typed draft mounted when a refresh fails', async () => {
        initKeaTests()
        silenceKeaLoadersErrors()
        const account: AccountApi = {
            id: 'account-1',
            name: 'Example account',
            notebooks: [],
            ignored_at: null,
            created_at: '2026-01-01T00:00:00Z',
            created_by: null,
            updated_at: null,
            tags: [],
        }
        const definition: CustomPropertyDefinitionApi = {
            id: 'property-1',
            name: 'Plan',
            display_type: 'text',
            target_type: 'account',
            is_canonical: false,
            has_workflow_reference: false,
            references: [],
            source: null,
            created_at: '2026-01-01T00:00:00Z',
            created_by: 1,
            updated_at: null,
        }
        const valuesUrl = '/api/projects/:project_id/accounts/:account_id/custom_property_values/'
        useMocks({
            get: {
                '/api/projects/:project_id/accounts/:account_id/': account,
                '/api/projects/:project_id/user_customer_analytics_config/@me/': {
                    pinned_properties: [{ kind: 'custom_property', id: definition.id }],
                },
                '/api/projects/:project_id/custom_property_definitions/': { count: 1, results: [definition] },
                '/api/projects/:project_id/account_relationship_definitions/': { count: 0, results: [] },
                '/api/projects/:project_id/accounts/:account_id/relationships/': [],
                [valuesUrl]: [
                    {
                        id: 'value-1',
                        definition_id: definition.id,
                        account_id: account.id,
                        value: 'Starter',
                        created_at: '2026-01-01T00:00:00Z',
                        created_by_id: 1,
                    },
                ],
            },
        })
        const { container } = render(
            <BindLogic logic={customerAnalyticsAccountSceneLogic} props={{ accountId: account.id }}>
                <AccountSidebar account={account} />
            </BindLogic>
        )
        await screen.findByText('Starter')
        fireEvent.click(container.querySelector('[data-attr="account-property-edit"]')!)
        fireEvent.change(screen.getByDisplayValue('Starter'), { target: { value: 'Draft to retain' } })
        useMocks({ get: { [valuesUrl]: () => [500, { detail: 'Unavailable' }] } })
        const logic = accountSidebarPropertiesLogic({
            projectId: projectLogic.values.currentProjectId!,
            accountId: account.id,
        })
        await act(async () => {
            await expectLogic(logic, () => logic.actions.loadPropertyData()).toFinishAllListeners()
        })
        expect(screen.getByText("Couldn't refresh pinned properties. These values might be out of date.")).toBeVisible()
        expect(screen.getByDisplayValue('Draft to retain')).toBeVisible()
    })
})
