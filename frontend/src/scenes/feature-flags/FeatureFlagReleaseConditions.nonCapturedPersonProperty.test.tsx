import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { FeatureFlagGroupType, FeatureFlagType } from '~/types'

import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

const UNSEEN_PROPERTY = '$survey_responded/0192e-abc'

function buildFilters(): FeatureFlagType['filters'] {
    const group: FeatureFlagGroupType = {
        properties: [],
        rollout_percentage: 100,
        variant: null,
        sort_key: 'group-1',
    }
    return { groups: [group], multivariate: null, payloads: {} }
}

// jsdom applies none of the Tailwind classes, so a plain text query also matches the copy of the
// row that sits in an inactive, `hidden` tab. The picker opens on the aggregated "All" tab, which
// is the only tab the person can see, so every assertion here has to skip the hidden copies.
function visibleOfferRow(): HTMLElement | undefined {
    return screen.queryAllByText('Select property:').find((row) => row.closest('.hidden') === null)
}

// Survey audience filters run on these conditions, and a survey targeting rule names a person
// property nobody has been given yet, so the picker has to offer the typed name.
describe('feature flag release conditions and unseen person properties', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/cohorts/': { results: [], next: null, count: 0 },
                '/api/projects/:team/feature_flags/1234/': {
                    id: 1234,
                    key: 'test-flag',
                    filters: { groups: [], multivariate: null, payloads: {} },
                },
                '/api/projects/:team/actions': { results: [] },
            },
            post: {
                '/api/environments/:team/query': { results: [] },
                '/api/projects/:team/feature_flags/user_blast_radius': () => [200, { affected: 0, total: 2 }],
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    async function openPickerAndSearch(allowed: boolean, onChange = jest.fn()): Promise<jest.Mock> {
        render(
            <Provider>
                <FeatureFlagReleaseConditions
                    id="1234"
                    filters={buildFilters()}
                    onChange={onChange}
                    allowNonCapturedPersonProperties={allowed}
                />
            </Provider>
        )

        fireEvent.click(await screen.findByText('Add condition'))
        // One change event rather than a keystroke per character: typing the whole name through
        // userEvent runs past the default test timeout on CI.
        fireEvent.change(screen.getByTestId('taxonomic-filter-searchfield'), {
            target: { value: UNSEEN_PROPERTY },
        })
        return onChange
    }

    it.each([
        ['offers the typed name when allowNonCapturedPersonProperties is set', true, true],
        ['leaves the picker unchanged without it', false, false],
    ])('%s', async (_name, allowed, expected) => {
        await openPickerAndSearch(allowed)

        await waitFor(() => {
            expect(visibleOfferRow() !== undefined).toBe(expected)
        })
    })

    it('commits a person property filter from the tab the picker opens on', async () => {
        const onChange = await openPickerAndSearch(true)

        await waitFor(() => {
            expect(visibleOfferRow()).not.toBeUndefined()
        })
        fireEvent.click(visibleOfferRow()!.closest('[data-attr="prop-filter-event-option-custom"]')!)

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledWith(
                expect.objectContaining({
                    groups: [
                        expect.objectContaining({
                            properties: [expect.objectContaining({ key: UNSEEN_PROPERTY, type: 'person' })],
                        }),
                    ],
                }),
                expect.anything()
            )
        })
    })
})
