/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'

describe('SessionRecordingsPlaylistTroubleshooting', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>
    const logicProps = { logicKey: 'troubleshooting-test', updateSearchParams: false }

    const mountWithBilling = async (billing: BillingType): Promise<void> => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': { results: [], has_next: false },
                '/api/environments/:team_id/session_recordings/properties': { results: [] },
                '/api/billing': () => [200, billing],
            },
        })
        initKeaTests()
        logic = sessionRecordingsPlaylistLogic(logicProps)
        logic.mount()
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    }

    afterEach(() => {
        cleanup()
        logic.unmount()
        billingLogic.unmount()
    })

    function renderTroubleshooting(): ReturnType<typeof render> {
        return render(
            <Provider>
                <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
                    <SessionRecordingsPlaylistTroubleshooting />
                </BindLogic>
            </Provider>
        )
    }

    // Regression: a team over its session replay quota gets recordings silently dropped
    // server-side, but this empty state used to only suggest retention windows and ad blockers.
    it('surfaces the session replay billing limit when the team is over it', async () => {
        await mountWithBilling({
            ...billingJson,
            products: billingJson.products.map((product) =>
                product.type === 'session_replay' ? { ...product, percentage_usage: 1.2 } : product
            ),
        })

        renderTroubleshooting()

        expect(screen.getByText(/hit your session replay billing limit/)).toBeInTheDocument()
    })

    it('does not mention a billing limit when the team is under it', async () => {
        await mountWithBilling(billingJson)

        renderTroubleshooting()

        expect(screen.queryByText(/billing limit/)).not.toBeInTheDocument()
    })
})
