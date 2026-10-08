import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { SelectorMatchChangeNotice } from 'scenes/insights/SelectorMatchChangeNotice'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType } from '~/types'

import { ActionSelectorMatchChangeApi } from 'products/actions/frontend/generated/api.schemas'

const insightProps = { dashboardItemId: 'new' as const }

describe('SelectorMatchChangeNotice', () => {
    const actionsRequest = jest.fn(() => [200, { results: [] }])
    let selectorMatchChanges: ActionSelectorMatchChangeApi[] = []
    const selectorMatchChangesRequest = jest.fn((_context: { request: Request }) => [200, selectorMatchChanges])

    beforeEach(() => {
        selectorMatchChanges = []
        useMocks({
            get: {
                '/api/projects/:team_id/actions/': actionsRequest,
                '/api/projects/:team_id/actions/selector_match_changes/': selectorMatchChangesRequest,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => cleanup())

    function setup(featureEnabled: boolean, actionId?: number): void {
        featureFlagLogic.actions.setFeatureFlags(featureEnabled ? [FEATURE_FLAGS.SELECTOR_MATCH_CHANGE_NOTICE] : [], {
            [FEATURE_FLAGS.SELECTOR_MATCH_CHANGE_NOTICE]: featureEnabled,
        })

        const vizDataLogic = insightVizDataLogic(insightProps)
        vizDataLogic.mount()
        vizDataLogic.actions.updateQuerySource({
            kind: NodeKind.TrendsQuery,
            series: actionId
                ? [{ kind: NodeKind.ActionsNode, id: actionId }]
                : [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
        } as TrendsQuery)

        render(
            <Provider>
                <SelectorMatchChangeNotice insightProps={insightProps} />
            </Provider>
        )
    }

    it.each([
        ['the feature flag is off', false, 42],
        ['the insight has no action series', true, undefined],
    ])('does not load actions when %s', (_name, featureEnabled, actionId) => {
        setup(featureEnabled, actionId)

        expect(actionsRequest).not.toHaveBeenCalled()
        expect(selectorMatchChangesRequest).not.toHaveBeenCalled()
    })

    it('loads only selector match changes for the insight action IDs', async () => {
        setup(true, 42)

        await waitFor(() => expect(selectorMatchChangesRequest).toHaveBeenCalledTimes(1))
        expect(actionsRequest).not.toHaveBeenCalled()
        const requestUrl = selectorMatchChangesRequest.mock.lastCall?.[0].request.url
        expect(requestUrl).not.toBeUndefined()
        expect(new URL(requestUrl ?? 'http://localhost').searchParams.get('action_ids')).toBe('42')
    })

    it('names each affected action, links to it, and lists its selectors', async () => {
        selectorMatchChanges = [
            { action_id: 42, action_name: 'Signup button clicked', selectors: ['div.btn.primary', '.cta > span'] },
        ]
        setup(true, 42)

        const actionLink = await screen.findByText('Signup button clicked')
        expect(actionLink.closest('a')).toHaveAttribute('href', expect.stringContaining(urls.action(42)))
        expect(screen.getByText('div.btn.primary')).toBeInTheDocument()
        expect(screen.getByText('.cta > span')).toBeInTheDocument()
        expect(screen.getByText('Read more about action selector matching')).toBeInTheDocument()
    })

    it('renders nothing when no action in the insight is affected', async () => {
        setup(true, 42)

        await waitFor(() => expect(selectorMatchChangesRequest).toHaveBeenCalledTimes(1))
        expect(screen.queryByText(/Counts in this insight are lower/)).not.toBeInTheDocument()
    })
})
