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

    it.each([
        ['offers the typed name when allowNonCapturedPersonProperties is set', true, true],
        ['leaves the picker unchanged without it', false, false],
    ])('%s', async (_name, allowed, expected) => {
        render(
            <Provider>
                <FeatureFlagReleaseConditions
                    id="1234"
                    filters={buildFilters()}
                    onChange={jest.fn()}
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

        await waitFor(() => {
            expect(screen.queryByText('Select property:') !== null).toBe(expected)
        })
    })
})
