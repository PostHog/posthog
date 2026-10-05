import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EmailTemplater } from './EmailTemplater'
import { EmailTemplate, emailTemplaterLogic } from './emailTemplaterLogic'

// The Unlayer editor loads its canvas from an external script, which jsdom cannot run.
jest.mock('react-email-editor', () => ({
    __esModule: true,
    default: () => <div data-attr="email-editor-canvas" />,
}))

const EMAIL_WITH_CONTENT: EmailTemplate = {
    design: null,
    html: '<div>Hello</div>',
    subject: 'Your weekly report',
    text: 'Hello',
    from: { integrationId: 1 },
    to: 'recipient@example.com',
}

describe('EmailTemplaterEditorPanel', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/': {
                    results: [
                        {
                            id: 'library-template',
                            name: 'Product update',
                            description: 'Monthly product update',
                            content: {
                                templating: 'liquid',
                                email: { subject: 'From the library', html: '<p>From the library</p>' },
                            },
                        },
                    ],
                },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ realm: 'cloud', is_debug: true } as any)
    })

    it('reaches the template picker from an email that already has content', async () => {
        render(<EmailTemplater value={EMAIL_WITH_CONTENT} onChange={jest.fn()} type="native_email" liveChanges />)
        emailTemplaterLogic.findMounted()!.actions.setIsModalOpen(true)

        await waitFor(() => expect(screen.getByText('Use a template')).toBeInTheDocument())
        await userEvent.click(screen.getByText('Use a template'))

        await waitFor(() => expect(screen.getByText('Choose a template')).toBeInTheDocument())
        expect(screen.getByText('Product update')).toBeInTheDocument()
    })
})
