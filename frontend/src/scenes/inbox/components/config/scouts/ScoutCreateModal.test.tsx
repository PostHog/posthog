import { cleanup, render } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ScoutCreateModal } from './ScoutCreateModal'

describe('ScoutCreateModal', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
            },
        })
    })

    afterEach(cleanup)

    it('includes a Slack destination in the create form', async () => {
        const { findByText } = render(
            <ScoutCreateModal
                isOpen
                onClose={jest.fn()}
                initialValues={{
                    name: 'signals-scout-ai-observability-daily-digest',
                    description: 'Creates a daily AI observability digest.',
                    body: 'Review AI observability and create one actionable digest.',
                }}
            />
        )

        expect(await findByText('Slack destination')).toBeTruthy()
        expect(await findByText('Connect a Slack workspace')).toBeTruthy()
    })
})
