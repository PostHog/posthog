import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { maxLogic } from 'scenes/max/maxLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HOMEPAGE_TAB_ID } from './constants'
import { HomepageAiInput } from './HomepageInput'

jest.mock('scenes/max/components/SidebarQuestionInput', () => ({
    SidebarQuestionInput: () => <div data-attr="mock-question-input" />,
}))

describe('HomepageAiInput', () => {
    const APPROVE_LABEL = 'I allow AI analysis in this organization'

    function renderInput(): HTMLElement {
        const { container } = render(
            <BindLogic logic={maxLogic} props={{ panelId: HOMEPAGE_TAB_ID }}>
                <HomepageAiInput />
            </BindLogic>
        )
        return container
    }

    beforeEach(() => {
        useMocks({
            patch: {
                '/api/organizations/:id': async ({ request }) => [
                    200,
                    {
                        ...MOCK_DEFAULT_ORGANIZATION,
                        ...((await request.json()) as Partial<typeof MOCK_DEFAULT_ORGANIZATION>),
                    },
                ],
            },
        })
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
    })

    it('approves AI data processing and swaps in the composer when the button is clicked', async () => {
        const container = renderInput()

        fireEvent.click(screen.getByText(APPROVE_LABEL))

        await waitFor(() =>
            expect(organizationLogic.values.currentOrganization?.is_ai_data_processing_approved).toBe(true)
        )
        expect(container.querySelector('[data-attr="mock-question-input"]')).toBeTruthy()
    })
})
