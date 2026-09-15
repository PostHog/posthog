import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type {
    AccountApi,
    AccountRelationshipApi,
    AccountRelationshipDefinitionApi,
    AccountRelationshipWriteApi,
    CustomPropertyDefinitionApi,
    CustomPropertyValueWriteApi,
    UserCustomerAnalyticsConfigApi,
} from '../../generated/api.schemas'
import { AccountSidebar } from '../../scenes/CustomerAnalyticsAccountScene/AccountSidebar'
import { accountSidebarConfigLogic } from '../../scenes/CustomerAnalyticsAccountScene/accountSidebarConfigLogic'
import { accountSidebarPropertiesLogic } from '../../scenes/CustomerAnalyticsAccountScene/accountSidebarPropertiesLogic'
import { customerAnalyticsAccountSceneLogic } from '../../scenes/CustomerAnalyticsAccountScene/customerAnalyticsAccountSceneLogic'
import { AccountPinnedPropertiesExpansion } from './AccountPinnedPropertiesExpansion'

const VALUES_URL = '/api/projects/:project_id/accounts/:account_id/custom_property_values/'
const RELATIONSHIPS_URL = '/api/projects/:project_id/accounts/:account_id/relationships/'
const DEFINITIONS_URL = '/api/projects/:project_id/custom_property_definitions/'
const CONFIG_URL = '/api/projects/:project_id/user_customer_analytics_config/@me/'
const FIELD_SELECTOR = '[data-attr="account-property-row"]'
const SAVE_ERROR = 'Could not save this property. Review the value and try again.'

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
const relationshipDefinition: AccountRelationshipDefinitionApi = {
    id: 'relationship-1',
    name: 'CSM',
    is_single_holder: true,
}
const members = [
    { id: 1, email: 'alex@example.com', first_name: '' },
    { id: 2, email: 'sam@example.com', first_name: '' },
]
const editCases = [
    { name: 'Plan', current: 'Starter', next: 'Growth', request: { definition: definition.id, value: 'Growth' } },
    {
        name: 'CSM',
        current: 'alex@example.com',
        next: 'sam@example.com',
        request: { definition: relationshipDefinition.id, user: 2 },
    },
] as const

function getField(name: string): HTMLElement {
    return screen.getByText(name).closest<HTMLElement>(FIELD_SELECTOR)!
}

async function changeDraft(name: string): Promise<void> {
    if (name === 'Plan') {
        fireEvent.change(screen.getByDisplayValue('Starter'), { target: { value: 'Growth' } })
    } else {
        await userEvent.click(getField(name).querySelector('[data-attr="account-relationship-members-input"]')!)
        await userEvent.click(await screen.findByText('sam@example.com'))
    }
}

function createAssignment(userId: number): AccountRelationshipApi {
    return {
        id: `assignment-${userId}`,
        definition: relationshipDefinition,
        user: members.find(({ id }) => id === userId)!,
        started_at: '2026-01-01T00:00:00Z',
        ended_at: null,
    }
}

describe('AccountPinnedPropertiesExpansion', () => {
    let previousAppContext: typeof window.POSTHOG_APP_CONTEXT
    let storedValue: CustomPropertyValueWriteApi['value']
    let assignments: AccountRelationshipApi[]
    let writes: (CustomPropertyValueWriteApi | AccountRelationshipWriteApi)[]
    let logic: ReturnType<typeof accountSidebarPropertiesLogic.build>

    const renderExpansion = async (): Promise<void> => {
        render(<AccountPinnedPropertiesExpansion accountId="account-1" />)
        logic = accountSidebarPropertiesLogic({
            projectId: projectLogic.values.currentProjectId!,
            accountId: 'account-1',
        })
        await act(async () => {
            await expectLogic(logic).toFinishAllListeners()
        })
        expect(within(getField('Plan')).getByText('Starter')).toBeVisible()
        expect(within(getField('CSM')).getByText('alex@example.com')).toBeVisible()
    }

    beforeEach(() => {
        previousAppContext = window.POSTHOG_APP_CONTEXT
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
                [AccessControlResourceType.CustomerAnalytics]: AccessControlLevel.Editor,
            },
        }
        storedValue = 'Starter'
        assignments = [createAssignment(1)]
        writes = []
        useMocks({
            get: {
                [CONFIG_URL]: {
                    pinned_properties: [
                        { kind: 'relationship', id: relationshipDefinition.id },
                        { kind: 'custom_property', id: definition.id },
                    ],
                },
                [DEFINITIONS_URL]: { count: 1, results: [definition] },
                '/api/projects/:project_id/account_relationship_definitions/': {
                    count: 1,
                    results: [relationshipDefinition],
                },
                '/api/organizations/:organization_id/members/': {
                    count: members.length,
                    next: null,
                    results: members.map((user) => ({ user })),
                },
                [VALUES_URL]: ({ params }) => [
                    {
                        id: `value-${params.account_id}`,
                        definition_id: definition.id,
                        account_id: params.account_id,
                        value: storedValue,
                        created_at: '2026-01-01T00:00:00Z',
                        created_by_id: 1,
                    },
                ],
                [RELATIONSHIPS_URL]: () => assignments,
            },
            post: {
                [VALUES_URL]: async ({ request }) => {
                    const body = (await request.json()) as CustomPropertyValueWriteApi
                    writes.push(body)
                    storedValue = body.value
                    return [201, { id: 'new-value', definition_id: body.definition, value: storedValue }]
                },
                [RELATIONSHIPS_URL]: async ({ request }) => {
                    const body = (await request.json()) as AccountRelationshipWriteApi
                    writes.push(body)
                    assignments = [createAssignment(body.user)]
                    return [201, assignments[0]]
                },
            },
        })
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
        window.POSTHOG_APP_CONTEXT = previousAppContext
    })

    it('opens one configurator and shares saved pins, but not canceled drafts, across expansions and the sidebar', async () => {
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
        const configWrites: UserCustomerAnalyticsConfigApi[] = []
        useMocks({
            get: { '/api/projects/:project_id/accounts/:account_id/': account },
            post: { '/api/projects/:project_id/accounts/:account_id/presence/': [] },
            patch: {
                [CONFIG_URL]: async ({ request }) => {
                    const body = (await request.json()) as UserCustomerAnalyticsConfigApi
                    configWrites.push(body)
                    return body
                },
            },
        })
        const { container } = render(
            <>
                <AccountPinnedPropertiesExpansion accountId={account.id} />
                <AccountPinnedPropertiesExpansion accountId="account-2" />
                <BindLogic logic={customerAnalyticsAccountSceneLogic} props={{ accountId: account.id }}>
                    <AccountSidebar account={account} />
                </BindLogic>
            </>
        )
        const expansions = container.querySelectorAll<HTMLElement>('[data-attr="account-pinned-properties-expansion"]')
        expect(expansions).toHaveLength(2)
        const sidebar = container.querySelector<HTMLElement>('[data-attr="account-sidebar"]')!
        const panels = [...expansions, sidebar]
        for (const panel of panels) {
            expect(await within(panel).findByText('Starter')).toBeVisible()
            expect(within(panel).getByText('alex@example.com')).toBeVisible()
            expect(within(panel).getByText('Properties')).toBeVisible()
        }

        await userEvent.click(within(expansions[0]).getByLabelText('Configure pinned properties'))
        let dialogs = await screen.findAllByRole('dialog', { hidden: true })
        expect(dialogs).toHaveLength(1)
        await userEvent.click(within(dialogs[0]).getByLabelText('Remove Plan'))
        for (const panel of panels) {
            expect(within(panel).getByText('Starter')).toBeVisible()
        }
        await userEvent.click(within(dialogs[0]).getByText('Cancel'))
        await waitFor(() => expect(screen.queryAllByRole('dialog', { hidden: true })).toHaveLength(0))
        expect(configWrites).toEqual([])
        for (const panel of panels) {
            expect(panel.querySelectorAll(FIELD_SELECTOR)).toHaveLength(2)
            expect(within(panel).getByText('Starter')).toBeVisible()
            expect(within(panel).getByText('alex@example.com')).toBeVisible()
        }

        await userEvent.click(within(expansions[1]).getByLabelText('Configure pinned properties'))
        dialogs = await screen.findAllByRole('dialog', { hidden: true })
        expect(dialogs).toHaveLength(1)
        expect(within(dialogs[0]).getByLabelText('Remove Plan')).toBeVisible()
        await userEvent.click(within(dialogs[0]).getByLabelText('Remove CSM'))
        const configLogic = accountSidebarConfigLogic({ projectId: projectLogic.values.currentProjectId! })
        await act(async () => {
            await expectLogic(configLogic, () => {
                fireEvent.click(within(dialogs[0]).getByText('Save'))
            }).toFinishAllListeners()
        })

        expect(configWrites).toEqual([{ pinned_properties: [{ kind: 'custom_property', id: definition.id }] }])
        await waitFor(() => expect(screen.queryAllByRole('dialog', { hidden: true })).toHaveLength(0))
        for (const panel of panels) {
            expect(panel.querySelectorAll(FIELD_SELECTOR)).toHaveLength(1)
            expect(within(panel).getByText('Plan')).toBeVisible()
            expect(within(panel).getByText('Starter')).toBeVisible()
            expect(within(panel).queryByText('CSM')).not.toBeInTheDocument()
            expect(within(panel).queryByText('alex@example.com')).not.toBeInTheDocument()
        }
    })

    it.each(editCases)(
        'discards canceled $name drafts and displays saved edits',
        async ({ name, current, next, request }) => {
            await renderExpansion()
            await userEvent.click(screen.getByLabelText(`Edit ${name}`))
            await changeDraft(name)
            fireEvent.click(within(getField(name)).getByText('Cancel'))

            expect(within(getField(name)).getByText(current)).toBeVisible()
            expect(screen.getByLabelText(`Edit ${name}`)).toBeVisible()
            expect(writes).toEqual([])

            await userEvent.click(screen.getByLabelText(`Edit ${name}`))
            if (name === 'Plan') {
                expect(screen.getByDisplayValue(current)).toBeVisible()
            } else {
                expect(within(getField(name)).getByText(current)).toBeVisible()
                expect(within(getField(name)).queryByText(next)).not.toBeInTheDocument()
            }
            await changeDraft(name)
            await act(async () => {
                await expectLogic(logic, () => {
                    fireEvent.click(within(getField(name)).getByText('Save'))
                }).toFinishAllListeners()
            })

            expect(writes).toEqual([request])
            expect(within(getField(name)).getByText(next)).toBeVisible()
            expect(getField(name).querySelector('input')).not.toBeInTheDocument()
            expect(screen.getByLabelText(`Edit ${name}`)).toBeVisible()
        }
    )

    it.each(editCases)(
        'keeps the $name draft and error after a failed save',
        async ({ name, current, next, request }) => {
            silenceKeaLoadersErrors()
            let releaseSave: () => void = () => {}
            const pendingSave = new Promise<void>((resolve) => {
                releaseSave = resolve
            })
            useMocks({
                post: {
                    [name === 'Plan' ? VALUES_URL : RELATIONSHIPS_URL]: async ({ request }) => {
                        writes.push((await request.json()) as CustomPropertyValueWriteApi | AccountRelationshipWriteApi)
                        await pendingSave
                        return [400, { detail: 'Invalid value' }]
                    },
                },
            })
            await renderExpansion()
            await userEvent.click(screen.getByLabelText(`Edit ${name}`))
            await changeDraft(name)
            const field = getField(name)
            fireEvent.click(within(field).getByText('Save'))
            await waitFor(() => expect(writes).toEqual([request]))
            expect(field.querySelector('input')).toBeDisabled()
            expect(within(field).getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true')
            fireEvent.click(within(field).getByText('Save'))

            await act(async () => {
                await expectLogic(logic, releaseSave).toFinishAllListeners()
            })

            expect(writes).toEqual([request])
            expect(screen.getByText(SAVE_ERROR)).toBeVisible()
            expect(field.querySelector('input')).toBeEnabled()
            expect(within(field).getByText('Save').closest('button')).not.toHaveAttribute('aria-disabled', 'true')
            if (name === 'Plan') {
                expect(screen.getByDisplayValue(next)).toBeVisible()
            } else {
                expect(within(field).getByText(next)).toBeVisible()
                expect(within(field).queryByText(current)).not.toBeInTheDocument()
            }
            fireEvent.click(within(field).getByText('Cancel'))
            expect(screen.queryByText(SAVE_ERROR)).not.toBeInTheDocument()
            expect(within(field).getByText(current)).toBeVisible()
        }
    )

    it.each([
        ['canonical', { is_canonical: true }],
        ['warehouse', { source: { id: 'source-1' } }],
    ])('hides editing for a %s property without hiding editable relationships', async (_, overrides) => {
        useMocks({ get: { [DEFINITIONS_URL]: { count: 1, results: [{ ...definition, ...overrides }] } } })
        await renderExpansion()

        expect(within(getField('Plan')).queryByLabelText('Edit Plan')).not.toBeInTheDocument()
        expect(getField('Plan').querySelector('input')).not.toBeInTheDocument()
        expect(screen.getByLabelText('Edit CSM')).toBeVisible()
    })

    it('shows values without edit controls to a resource-level viewer', async () => {
        window.POSTHOG_APP_CONTEXT!.resource_access_control![AccessControlResourceType.CustomerAnalytics] =
            AccessControlLevel.Viewer
        await renderExpansion()

        for (const { name } of editCases) {
            expect(within(getField(name)).queryByLabelText(`Edit ${name}`)).not.toBeInTheDocument()
            expect(getField(name).querySelector('input')).not.toBeInTheDocument()
        }
        expect(writes).toEqual([])
    })
})
