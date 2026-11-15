import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { SeriesNode } from '../seriesNode'
import { SaveAsActionBanner } from './SaveAsActionBanner'
import { makeSeriesNode } from './testHelpers'

function renderBanner(node: SeriesNode): ReturnType<typeof render> {
    return render(
        <Provider>
            <SaveAsActionBanner node={node} />
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
            get: { '/api/projects/:team/actions/': { results: [] } },
            post: {
                '/api/projects/:team/actions/': () => [200, { id: 42, name: 'Test Action', steps: [] }],
            },
        })
        actionsModel.mount()
    })

    describe('conditional rendering', () => {
        it.each([
            [
                'autocapture with $el_text',
                makeSeriesNode({
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
                makeSeriesNode({
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
                makeSeriesNode({
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
            ['non-autocapture event', makeSeriesNode({ event: '$pageview', name: '$pageview' })],
            [
                'autocapture with no element properties',
                makeSeriesNode({
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
            ['autocapture with empty properties', makeSeriesNode({ properties: [] })],
            ['action type', makeSeriesNode({ kind: NodeKind.ActionsNode, id: 123, name: 'My Action' })],
            [
                'autocapture with only negated operators',
                makeSeriesNode({
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

    describe('Save as action button', () => {
        it('opens the shared save-as-action dialog when clicked', async () => {
            renderBanner(
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                })
            )

            await userEvent.click(screen.getAllByTestId('autocapture-save-as-action')[0])

            await waitFor(() => {
                expect(screen.getByDisplayValue('Autocapture: "Submit"')).toBeInTheDocument()
            })
        })
    })

    describe('dismissal', () => {
        it('hides the banner when close button is clicked', async () => {
            const { container } = renderBanner(
                makeSeriesNode({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                })
            )
            expect(screen.getByText(/Save this autocapture filter as a reusable action/)).toBeInTheDocument()

            const closeButton = container.querySelector('.LemonBanner [aria-label="close"]') as HTMLElement
            await userEvent.click(closeButton)

            await waitFor(() => {
                expect(screen.queryByText(/Save this autocapture filter as a reusable action/)).not.toBeInTheDocument()
            })
        })
    })
})
