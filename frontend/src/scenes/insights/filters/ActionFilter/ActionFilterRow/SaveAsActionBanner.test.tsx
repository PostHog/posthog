import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { initKeaTests } from '~/test/init'
import { EntityTypes, PropertyFilterType, PropertyOperator } from '~/types'

import { LocalFilter } from '../entityFilterLogic'
import { SaveAsActionBanner } from './SaveAsActionBanner'
import { makeFilter } from './testHelpers'

function renderBanner(filter: LocalFilter): ReturnType<typeof render> {
    return render(
        <Provider>
            <SaveAsActionBanner filter={filter} />
        </Provider>
    )
}

describe('SaveAsActionBanner', () => {
    afterEach(async () => {
        cleanup()
        await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
        })
        document.querySelectorAll('body > div:not(#root)').forEach((el) => el.remove())
    })

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/actions/': { results: [] },
            },
            post: {
                '/api/projects/:team/actions/': () => [200, { id: 42, name: 'Test Action', steps: [] }],
            },
        })
        actionsModel.mount()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.AUTOCAPTURE_SAVE_AS_ACTION]: true })
    })

    describe('conditional rendering', () => {
        it.each([
            [
                'autocapture with $el_text',
                makeFilter({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
            ],
            [
                'autocapture with selector',
                makeFilter({
                    properties: [
                        {
                            key: 'selector',
                            value: '.btn',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
            ],
            [
                'autocapture with text and selector',
                makeFilter({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                        {
                            key: 'selector',
                            value: '.btn',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
            ],
        ])('renders banner for %s', (_description, filter) => {
            renderBanner(filter)
            expect(screen.getByText(/Save this autocapture filter as a reusable action/)).toBeInTheDocument()
        })

        it.each([
            ['non-autocapture event', makeFilter({ id: '$pageview', name: '$pageview' })],
            [
                'autocapture with no element properties',
                makeFilter({
                    properties: [
                        {
                            key: '$browser',
                            value: 'Chrome',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
            ],
            ['autocapture with empty properties', makeFilter({ properties: [] })],
            ['action type', makeFilter({ id: '123', name: 'My Action', type: EntityTypes.ACTIONS })],
            [
                'autocapture with only negated operators',
                makeFilter({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.NotIContains,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
            ],
        ])('does not render banner for %s', (_description, filter) => {
            renderBanner(filter)
            expect(screen.queryByText(/Save this autocapture filter as a reusable action/)).not.toBeInTheDocument()
        })
    })

    describe('banner content', () => {
        it('shows "Save as action" button', () => {
            const filter = makeFilter({
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            })
            renderBanner(filter)
            expect(screen.getAllByTestId('autocapture-save-as-action')[0]).toBeInTheDocument()
        })
    })

    describe('dialog interaction', () => {
        it('opens dialog with pre-filled name when "Save as action" is clicked', async () => {
            const filter = makeFilter({
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            })
            renderBanner(filter)

            await userEvent.click(screen.getAllByTestId('autocapture-save-as-action')[0])

            await waitFor(() => {
                expect(screen.getByDisplayValue('Autocapture: "Submit"')).toBeInTheDocument()
            })
        })

        it.each([
            [
                'text property',
                makeFilter({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                }),
                'Autocapture: "Submit"',
            ],
            [
                'selector property',
                makeFilter({
                    properties: [
                        {
                            key: 'selector',
                            value: '.btn-primary',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                'Autocapture: .btn-primary',
            ],
            [
                'href property',
                makeFilter({
                    properties: [
                        {
                            key: 'href',
                            value: '/foo',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                }),
                'Autocapture: link "/foo"',
            ],
        ])('pre-fills name from %s', async (_description, filter, expectedName) => {
            renderBanner(filter)

            await userEvent.click(screen.getAllByTestId('autocapture-save-as-action')[0])

            await waitFor(() => {
                expect(screen.getByDisplayValue(expectedName)).toBeInTheDocument()
            })
        })
    })

    describe('action creation', () => {
        it('calls the API with the correct action step', async () => {
            let capturedBody: any = null
            useMocks({
                post: {
                    '/api/projects/:team/actions/': async (req) => {
                        capturedBody = await req.json()
                        return [200, { id: 42, name: capturedBody.name, steps: capturedBody.steps }]
                    },
                },
            })

            const filter = makeFilter({
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                    {
                        key: 'selector',
                        value: '.btn',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Element,
                    },
                ],
            })
            renderBanner(filter)

            await userEvent.click(screen.getAllByTestId('autocapture-save-as-action')[0])

            await waitFor(() => {
                expect(screen.getByDisplayValue('Autocapture: "Submit"')).toBeInTheDocument()
            })

            const submitButton = screen.getByRole('button', { name: 'Submit' })
            await userEvent.click(submitButton)

            await waitFor(() => {
                expect(capturedBody).not.toBeNull()
            })
            expect(capturedBody.name).toBe('Autocapture: "Submit"')
            expect(capturedBody.steps).toHaveLength(1)
            expect(capturedBody.steps[0].event).toBe('$autocapture')
            expect(capturedBody.steps[0].text).toBe('Submit')
            expect(capturedBody.steps[0].text_matching).toBe('exact')
            expect(capturedBody.steps[0].selector).toBe('.btn')
        })
    })

    describe('dismissal', () => {
        it('hides the banner when close button is clicked', async () => {
            const filter = makeFilter({
                properties: [
                    {
                        key: '$el_text',
                        value: 'Submit',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            })
            const { container } = renderBanner(filter)
            expect(screen.getByText(/Save this autocapture filter as a reusable action/)).toBeInTheDocument()

            const closeButton = container.querySelector('.LemonBanner [aria-label="close"]') as HTMLElement
            await userEvent.click(closeButton)

            await waitFor(() => {
                expect(screen.queryByText(/Save this autocapture filter as a reusable action/)).not.toBeInTheDocument()
            })
        })
    })
})
