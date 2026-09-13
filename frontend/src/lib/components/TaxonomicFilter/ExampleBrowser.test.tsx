import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'

import { TaxonomicFilter } from './TaxonomicFilter'
import { TaxonomicFilterGroupType } from './types'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('ExampleBrowser', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': { results: [], count: 0 },
                '/api/projects/:team/property_definitions': ({ request }) => {
                    const matches = new URL(request.url).searchParams.get('search') === 'pl'
                    return [200, { results: matches ? [{ id: 'd1', name: 'plan' }] : [], count: matches ? 1 : 0 }]
                },
                '/api/projects/:team/actions': { results: [] },
            },
            post: {
                '/api/environments/:team/query/EventsQuery/': {
                    results: [
                        [
                            {
                                uuid: 'e1',
                                event: 'checkout completed',
                                timestamp: '2025-01-01T00:00:00Z',
                                distinct_id: 'user-1',
                                properties: { plan: 'pro', $browser: 'Chrome' },
                            },
                        ],
                    ],
                },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TAXONOMIC_FILTER_EXAMPLE_BROWSER]: true })
    })

    afterEach(() => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        cleanup()
    })

    it('opens from the empty list and selects a property from a recent event', async () => {
        const onChange = jest.fn()
        render(
            <Provider>
                <TaxonomicFilter
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    eventNames={['checkout completed']}
                    onChange={onChange}
                />
            </Provider>
        )

        // Hidden tabs render their own empty state, so more than one open button exists.
        await userEvent.click((await screen.findAllByTestId('taxonomic-example-browser-open'))[0])

        expect(await screen.findByText('plan')).toBeInTheDocument()
        expect(screen.queryByText('$browser')).not.toBeInTheDocument()

        await userEvent.click(screen.getByText('plan'))

        expect(onChange).toHaveBeenCalledWith(
            expect.objectContaining({ type: TaxonomicFilterGroupType.EventProperties }),
            'plan',
            { name: 'plan' }
        )
    })

    it('keeps the hidden list from opening a definition popover while the browser is open', async () => {
        render(
            <Provider>
                <TaxonomicFilter
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    eventNames={['checkout completed']}
                    onChange={jest.fn()}
                />
            </Provider>
        )
        await userEvent.click((await screen.findAllByTestId('taxonomic-example-browser-open'))[0])
        expect(await screen.findByTestId('taxonomic-example-browser-key')).toBeInTheDocument()

        await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'pl')

        expect(await screen.findByTestId('taxonomic-example-browser-key')).toBeInTheDocument()
        expect(screen.queryByTestId('definition-popover-pin')).not.toBeInTheDocument()
    })
})
