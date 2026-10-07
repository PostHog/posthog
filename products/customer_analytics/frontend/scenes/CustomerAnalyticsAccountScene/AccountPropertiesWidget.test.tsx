import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AccountApi, CustomPropertyDefinitionApi } from '../../generated/api.schemas'
import { AccountPropertiesWidget } from './AccountPropertiesWidget'
import type { AccountWidgetPropertyReference } from './accountPropertiesWidgetConfig'
import { accountPropertiesWidgetLogic } from './accountPropertiesWidgetLogic'
import { accountPropertyDataLogic } from './accountPropertyDataLogic'
import { accountSidebarConfigLogic } from './accountSidebarConfigLogic'
import { accountSidebarPropertiesLogic } from './accountSidebarPropertiesLogic'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    userHasAccess: () => true,
}))

const PROJECT_ID = MOCK_DEFAULT_TEAM.id
const ACCOUNT_ID = '11111111-1111-4111-8111-111111111111'
const ACCOUNT_URL = '/api/projects/:project_id/accounts/:account_id/'
const DEFINITIONS_URL = '/api/projects/:project_id/custom_property_definitions/'
const EMPTY_PAGE = { count: 0, results: [] }
const nativeReferences: AccountWidgetPropertyReference[] = [{ kind: 'account', key: 'billing_id' }]
const account: AccountApi = {
    id: ACCOUNT_ID,
    name: 'Example account',
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    properties: { billing_id: 'billing-example' },
}

function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

function renderWidget(references = nativeReferences): ReturnType<typeof render> {
    return render(
        <AccountPropertiesWidget
            projectId={PROJECT_ID}
            accountId={ACCOUNT_ID}
            instanceId="first"
            initialConfig={{ properties: references }}
        />
    )
}

async function waitForNativeAccount(): Promise<void> {
    await waitFor(() =>
        expect(accountPropertyDataLogic({ projectId: PROJECT_ID, accountId: ACCOUNT_ID }).values.account).toEqual(
            account
        )
    )
}

async function finishRequests<T>(pending: { resolve: (value: T) => void }, value: T): Promise<void> {
    await act(async () => {
        pending.resolve(value)
        await expectLogic(accountSidebarConfigLogic({ projectId: PROJECT_ID })).toFinishAllListeners()
    })
}

describe('AccountPropertiesWidget source resolution', () => {
    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                [ACCOUNT_URL]: account,
                [DEFINITIONS_URL]: EMPTY_PAGE,
                '/api/projects/:project_id/account_relationship_definitions/': EMPTY_PAGE,
                '/api/projects/:project_id/user_customer_analytics_config/@me/': { pinned_properties: [] },
            },
        })
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
    })

    it.each(['pending', 'failed'] as const)(
        'shows loaded native-only values while definitions are %s',
        async (state) => {
            const pending = createDeferred<typeof EMPTY_PAGE>()
            useMocks({
                get: {
                    [DEFINITIONS_URL]: () =>
                        state === 'pending' ? pending.promise : [500, { detail: 'Definitions unavailable' }],
                },
            })
            const { container } = renderWidget()
            try {
                const definitions = accountSidebarConfigLogic({ projectId: PROJECT_ID })
                await waitFor(() =>
                    state === 'pending'
                        ? expect(definitions.values.availableDefinitionsLoading).toBe(true)
                        : expect(definitions.values.availableDefinitionsLoadFailed).toBe(true)
                )
                await waitForNativeAccount()
                expect(await screen.findByText('billing-example')).toBeVisible()
                expect(
                    container.querySelector('[data-attr="account-properties-widget-loading"]')
                ).not.toBeInTheDocument()
                expect(screen.queryByText('Could not load properties.')).not.toBeInTheDocument()
                expect(
                    screen.queryByText('Could not refresh properties. These values may be out of date.')
                ).not.toBeInTheDocument()
            } finally {
                await finishRequests(pending, EMPTY_PAGE)
            }
        }
    )

    it('retries a native account failure without waiting for or refetching pending definitions', async () => {
        const pendingDefinitions = createDeferred<typeof EMPTY_PAGE>()
        const retriedAccount = createDeferred<AccountApi>()
        let failAccount = true
        const accountGet = jest.fn(() =>
            failAccount ? [500, { detail: 'Account unavailable' }] : retriedAccount.promise
        )
        const definitionsGet = jest.fn(() => pendingDefinitions.promise)
        useMocks({ get: { [ACCOUNT_URL]: accountGet, [DEFINITIONS_URL]: definitionsGet } })
        renderWidget()
        try {
            expect(await screen.findByText('Could not load properties.')).toBeVisible()
            await waitFor(() => expect(definitionsGet).toHaveBeenCalledTimes(1))
            const retryButton = screen.getAllByText('Try again')[0].closest('button')!
            expect(retryButton).not.toHaveAttribute('aria-disabled', 'true')
            failAccount = false
            act(() => {
                fireEvent.click(retryButton)
                fireEvent.click(retryButton)
            })
            await waitFor(() => expect(accountGet).toHaveBeenCalledTimes(2))
            await act(async () => {
                retriedAccount.resolve(account)
            })
            expect(await screen.findByText('billing-example')).toBeVisible()
            expect(accountGet).toHaveBeenCalledTimes(2)
            expect(definitionsGet).toHaveBeenCalledTimes(1)
            const definitions = accountSidebarConfigLogic({ projectId: PROJECT_ID })
            expect(definitions.values.availableDefinitions).toBeNull()
            expect(definitions.values.availableDefinitionsLoading).toBe(true)
        } finally {
            await act(async () => {
                retriedAccount.resolve(account)
                pendingDefinitions.resolve(EMPTY_PAGE)
                await expectLogic(accountSidebarConfigLogic({ projectId: PROJECT_ID })).toFinishAllListeners()
            })
        }
    })

    it('shows newly configured values through rerender without remounting instances or changing pins', async () => {
        const definition: CustomPropertyDefinitionApi = {
            id: '22222222-2222-4222-8222-222222222222',
            name: 'Plan',
            display_type: 'text',
            target_type: 'account',
            is_canonical: false,
            has_workflow_reference: false,
            source: null,
            references: [],
            created_at: '2026-01-01T00:00:00Z',
            created_by: 1,
            updated_at: null,
        }
        useMocks({
            get: {
                [DEFINITIONS_URL]: { count: 1, results: [definition] },
                '/api/projects/:project_id/accounts/:account_id/custom_property_values/': [
                    {
                        id: 'value-1',
                        account_id: ACCOUNT_ID,
                        definition_id: definition.id,
                        value: 'Starter',
                        created_at: '2026-01-01T00:00:00Z',
                        created_by_id: 1,
                    },
                ],
                '/api/projects/:project_id/accounts/:account_id/relationships/': [],
            },
        })
        const { rerender } = renderWidget([])
        const definitions = accountSidebarConfigLogic({ projectId: PROJECT_ID })
        await act(async () => {
            await expectLogic(definitions).toFinishAllListeners()
        })
        const native = accountPropertiesWidgetLogic.findMounted({
            projectId: PROJECT_ID,
            accountId: ACCOUNT_ID,
            instanceId: 'first',
        })
        const properties = accountSidebarPropertiesLogic.findMounted({
            projectId: PROJECT_ID,
            accountId: ACCOUNT_ID,
            instanceId: 'view:first',
        })
        expect(native).not.toBeNull()
        expect(properties).not.toBeNull()
        expect(
            screen.getByText("No properties selected. Use the tile's Edit action to choose properties.")
        ).toBeVisible()
        rerender(
            <AccountPropertiesWidget
                projectId={PROJECT_ID}
                accountId={ACCOUNT_ID}
                instanceId="first"
                initialConfig={{ properties: [{ kind: 'custom_property', id: definition.id }] }}
            />
        )
        expect(await screen.findByText('Starter')).toBeVisible()
        rerender(
            <AccountPropertiesWidget
                projectId={PROJECT_ID}
                accountId={ACCOUNT_ID}
                instanceId="first"
                initialConfig={{ properties: nativeReferences }}
            />
        )
        expect(await screen.findByText('billing-example')).toBeVisible()
        expect(screen.queryByText('Starter')).not.toBeInTheDocument()
        expect(
            accountPropertiesWidgetLogic.findMounted({
                projectId: PROJECT_ID,
                accountId: ACCOUNT_ID,
                instanceId: 'first',
            })
        ).toBe(native)
        expect(
            accountSidebarPropertiesLogic.findMounted({
                projectId: PROJECT_ID,
                accountId: ACCOUNT_ID,
                instanceId: 'view:first',
            })
        ).toBe(properties)
        expect(definitions.values.config?.pinned_properties).toEqual([])
    })

    it('does not show a definitions refresh warning for a native-only widget', async () => {
        renderWidget()
        const definitions = accountSidebarConfigLogic({ projectId: PROJECT_ID })
        await act(async () => {
            await expectLogic(definitions).toFinishAllListeners()
        })
        expect(await screen.findByText('billing-example')).toBeVisible()
        useMocks({ get: { [DEFINITIONS_URL]: () => [500, { detail: 'Definitions unavailable' }] } })
        await act(async () => {
            await expectLogic(definitions, () => definitions.actions.loadAvailableDefinitions()).toFinishAllListeners()
        })
        expect(screen.getByText('billing-example')).toBeVisible()
        expect(
            screen.queryByText('Could not refresh properties. These values may be out of date.')
        ).not.toBeInTheDocument()
    })

    it.each(['pending', 'failed'] as const)('keeps definition %s gates for a mixed-source widget', async (state) => {
        const pending = createDeferred<typeof EMPTY_PAGE>()
        useMocks({
            get: {
                [DEFINITIONS_URL]: () =>
                    state === 'pending' ? pending.promise : [500, { detail: 'Definitions unavailable' }],
            },
        })
        const { container } = renderWidget([
            ...nativeReferences,
            { kind: 'custom_property', id: '22222222-2222-4222-8222-222222222222' },
        ])
        try {
            await waitForNativeAccount()
            if (state === 'pending') {
                expect(container.querySelector('[data-attr="account-properties-widget-loading"]')).toBeInTheDocument()
            } else {
                expect(await screen.findByText('Could not load properties.')).toBeVisible()
            }
            expect(screen.queryByText('billing-example')).not.toBeInTheDocument()
        } finally {
            await finishRequests(pending, EMPTY_PAGE)
        }
    })

    it.each(['pending', 'failed'] as const)('keeps native account %s gates for a native-only widget', async (state) => {
        const pending = createDeferred<AccountApi>()
        useMocks({
            get: {
                [ACCOUNT_URL]: () => (state === 'pending' ? pending.promise : [500, { detail: 'Account unavailable' }]),
            },
        })
        const { container } = renderWidget()
        try {
            await waitFor(() =>
                expect(accountSidebarConfigLogic({ projectId: PROJECT_ID }).values.availableDefinitions).not.toBeNull()
            )
            if (state === 'pending') {
                expect(container.querySelector('[data-attr="account-properties-widget-loading"]')).toBeInTheDocument()
            } else {
                expect(await screen.findByText('Could not load properties.')).toBeVisible()
            }
            expect(screen.queryByText('billing-example')).not.toBeInTheDocument()
        } finally {
            await finishRequests(pending, account)
        }
    })
})
