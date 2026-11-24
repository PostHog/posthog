import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('ObjectTags', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it('removes a tag via the x without collapsing edit mode', async () => {
        const onChange = jest.fn()
        const { container } = render(
            <Provider>
                <ObjectTags
                    tags={['alpha', 'beta']}
                    onChange={onChange}
                    saving={false}
                    tagsAvailable={['alpha', 'beta']}
                />
            </Provider>
        )

        await userEvent.click(within(container).getByText('Edit tags'))

        const closeButtons = container.querySelectorAll('.LemonSnack__close button')
        expect(closeButtons).toHaveLength(2)

        await userEvent.click(closeButtons[0] as HTMLElement)

        // The click must actually remove the tag (not just close editing before it lands)
        expect(onChange).toHaveBeenCalledWith(['beta'])
        expect(container.querySelector('input[type="text"]')).not.toBeNull()
    })

    it('requests usage counts for objectType and hides already-present tags from the autocomplete dropdown', async () => {
        const requestedUrls: URL[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/tags': ({ request }) => {
                    requestedUrls.push(new URL(request.url))
                    return [
                        200,
                        {
                            results: [
                                { tag: 'churn-risk', count: 42 },
                                { tag: 'churn_risk', count: 3 },
                                { tag: 'active trial', count: 10 },
                            ],
                            next: null,
                            count: 3,
                        },
                    ]
                },
            },
        })

        const { container } = render(
            <Provider>
                <ObjectTags tags={['active trial', 'tae']} onChange={jest.fn()} saving={false} objectType="account" />
            </Provider>
        )

        await userEvent.click(within(container).getByText('Edit tags'))

        await waitFor(() => expect(requestedUrls.length).toBeGreaterThan(0))
        expect(requestedUrls[0].searchParams.get('object_type')).toBe('account')
        expect(requestedUrls[0].searchParams.get('include_counts')).toBe('true')

        expect(await screen.findByText('churn-risk')).toBeInTheDocument()
        expect(screen.getByText('42')).toBeInTheDocument()
        expect(screen.getByText('churn_risk')).toBeInTheDocument()
        expect(screen.getByText('3')).toBeInTheDocument()

        // Already-present tags stay as removable snacks and are omitted from the dropdown
        expect(screen.queryByText('Add "tae"')).not.toBeInTheDocument()
        expect(screen.queryByText('10')).not.toBeInTheDocument()
        expect(within(container).getByText('active trial')).toBeInTheDocument()
        expect(within(container).getByText('tae')).toBeInTheDocument()
        expect(container.querySelectorAll('.LemonSnack__close button')).toHaveLength(2)
    })
})
