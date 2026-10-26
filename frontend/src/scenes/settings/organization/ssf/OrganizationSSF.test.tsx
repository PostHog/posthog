import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import type { PatchedSSFConfigurationApi } from '~/generated/core/api.schemas'
import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import { OrganizationSSF } from './OrganizationSSF'
import { SSF_SETTINGS } from './ssfSettingsFixtures'

const ssfFeature = { key: AvailableFeature.SSF, name: 'Shared Signals Framework (SSF)' }

describe('OrganizationSSF', () => {
    it.each([
        { entitled: false, catalogIncludesSSF: true, expectedText: ssfFeature.name },
        { entitled: false, catalogIncludesSSF: false, expectedText: /Your plan does not include SSF/ },
        { entitled: true, catalogIncludesSSF: true, expectedText: 'Enable SSF' },
    ])(
        'gates configuration with entitlement=$entitled and billing metadata=$catalogIncludesSSF',
        async ({ entitled, catalogIncludesSSF, expectedText }) => {
            let configurationRequests = 0
            let configuration = SSF_SETTINGS
            const updates: unknown[] = []
            let finishSave!: () => void
            const pendingSave = new Promise<void>((resolve) => {
                finishSave = resolve
            })
            useMocks({
                get: {
                    '/api/billing': {
                        ...billingJson,
                        products: billingJson.products.map((product, index) =>
                            catalogIncludesSSF && index === 0
                                ? { ...product, features: [...product.features, ssfFeature] }
                                : product
                        ),
                    },
                    '/api/organizations/:organization/ssf': () => {
                        configurationRequests++
                        return [200, configuration]
                    },
                    '/api/organizations/:organization/ssf/connections': () => {
                        configurationRequests++
                        return [200, []]
                    },
                    '/api/organizations/:organization/ssf/streams': () => {
                        configurationRequests++
                        return [200, []]
                    },
                },
                patch: {
                    '/api/organizations/:organization/ssf/configuration': async ({ request }) => {
                        const update = (await request.json()) as PatchedSSFConfigurationApi
                        updates.push(update)
                        await pendingSave
                        configuration = { ...configuration, ...update }
                        return [200, configuration]
                    },
                },
            })
            initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
                ...MOCK_DEFAULT_ORGANIZATION,
                available_product_features: entitled ? [ssfFeature] : [],
            })
            billingLogic.mount()
            await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

            render(<OrganizationSSF />)
            expect(await screen.findByText(expectedText)).toBeInTheDocument()
            expect(configurationRequests).toBe(entitled ? 3 : 0)
            if (!entitled) {
                expect(screen.queryByText('Connections')).not.toBeInTheDocument()
                expect(screen.queryByText('Save')).not.toBeInTheDocument()
            } else {
                const toggle = (): HTMLElement => screen.getByLabelText('Enable SSF')
                fireEvent.click(toggle())
                await waitFor(() => expect(updates).toEqual([{ enabled: false }]))
                expect(toggle()).toBeDisabled()
                expect(toggle()).toHaveAttribute('aria-checked', 'true')
                fireEvent.click(toggle())
                expect(updates).toHaveLength(1)
                finishSave()
                await waitFor(() => expect(screen.queryByText('Connections')).not.toBeInTheDocument())
                for (const label of [
                    'Additional outgoing event types',
                    'Save',
                    'Streams',
                    'Transmitter discovery',
                    'Rotate signing key',
                ]) {
                    expect(screen.queryByText(label)).not.toBeInTheDocument()
                }
                expect(toggle()).toHaveAttribute('aria-checked', 'false')
                expect(toggle()).not.toBeDisabled()
                fireEvent.click(toggle())
                expect(await screen.findByText('Connections')).toBeInTheDocument()
                expect(screen.getByText('Additional outgoing event types')).toBeInTheDocument()
                expect(updates).toEqual([{ enabled: false }, { enabled: true }])
            }
        }
    )
})
