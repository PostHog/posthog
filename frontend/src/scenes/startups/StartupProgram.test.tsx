/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { StartupProgramLabel } from '~/types'

import { StartupProgram } from './StartupProgram'
import { startupProgramLogic } from './startupProgramLogic'

describe('StartupProgram', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it.each(
        [undefined, 'yc'].flatMap((referrer) =>
            [
                {
                    credits: 100,
                    renews: false,
                    message: "Your YC credits expire on March 20, 2024 and won't renew.",
                },
                { credits: 0, renews: false, message: "Your YC credits are used up and won't renew." },
                {
                    credits: 0,
                    renews: true,
                    message:
                        "You've used this year's YC credits, so you pay for usage until they renew on March 20, 2024.",
                },
                { credits: 100, renews: true, message: /Your credits will renew automatically/ },
                { credits: 100, renews: undefined, message: /Your credits will renew automatically/ },
            ].map((state) => ({ referrer, ...state }))
        )
    )(
        'shows the current YC status on /startups/$referrer with $credits credits and renews=$renews',
        async ({ referrer, credits, renews, message }) => {
            useMocks({
                get: {
                    '/api/billing': [
                        200,
                        {
                            ...billingJson,
                            startup_program_label: StartupProgramLabel.YC,
                            startup_program_credits_renew: renews,
                            discount_amount_usd: credits,
                            amount_off_expires_at: '2024-03-20T00:00:00Z',
                            is_annual_plan_customer: false,
                        },
                    ],
                },
            })
            billingLogic.mount()
            await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

            render(
                <BindLogic logic={startupProgramLogic} props={{ referrer }}>
                    <StartupProgram />
                </BindLogic>
            )

            const title = referrer ? "You're in the YC Program" : 'You are already in the YC Program'
            const notice = within(screen.getByText(title).closest<HTMLElement>('[data-slot="card"]')!)
            expect(notice.getByText(message)).toBeInTheDocument()
            if (renews === false) {
                expect(notice.queryByText(/Your credits will renew automatically/)).not.toBeInTheDocument()
            }
        }
    )
})
