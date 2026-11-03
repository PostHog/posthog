import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EmailSenderSummary } from './EmailSenderSummary'
import { EmailTemplaterLogicProps, emailTemplaterLogic } from './emailTemplaterLogic'

const OWN_SENDER = {
    id: 5,
    kind: 'email',
    display_name: 'Acme <hello@acme.example.com>',
    config: { name: 'Acme', email: 'hello@acme.example.com', verified: true },
}
const SANDBOX_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'Acme via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', name: 'Acme via PostHog', email: 'sandbox@example.com', verified: true },
}

describe('EmailSenderSummary', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
                '/api/projects/:team_id/integrations/': { results: [OWN_SENDER, SANDBOX_SENDER] },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
    })

    afterEach(cleanup)

    it.each([
        ['the own sender', OWN_SENDER.id, 'Acme'],
        ['the sandbox sender', SANDBOX_SENDER.id, 'Choose who this email comes from'],
    ])('shows a transactional template sending from %s', async (_name, integrationId, expectedText) => {
        const props: EmailTemplaterLogicProps = {
            type: 'native_email_transactional_template',
            value: { subject: 'Hello', text: 'Hello', html: '<div>Hello</div>', from: { integrationId } } as any,
            onChange: jest.fn(),
        }
        const logic = emailTemplaterLogic(props)
        logic.mount()
        await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsSuccess'])

        render(
            <BindLogic logic={emailTemplaterLogic} props={props}>
                <EmailSenderSummary />
            </BindLogic>
        )

        expect(await screen.findByText(expectedText)).toBeInTheDocument()
        expect(screen.queryByText('Acme via PostHog')).not.toBeInTheDocument()
        logic.unmount()
    })
})
