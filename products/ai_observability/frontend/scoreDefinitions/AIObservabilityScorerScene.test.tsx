import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import {
    llmAnalyticsScoreDefinitionsCreate,
    llmAnalyticsScoreDefinitionsList,
    llmAnalyticsScoreDefinitionsRetrieve,
    llmAnalyticsScoreDefinitionsVersionsList,
} from '../generated/api'
import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { scene } from './AIObservabilityScorerScene'
import { scorerLogic } from './scorerLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    llmAnalyticsScoreDefinitionsCreate: jest.fn(),
    llmAnalyticsScoreDefinitionsList: jest.fn(),
    llmAnalyticsScoreDefinitionsRetrieve: jest.fn(),
    llmAnalyticsScoreDefinitionsVersionsList: jest.fn(),
}))

const source: ScoreDefinitionApi = {
    id: 'source-scorer',
    name: 'Answer quality',
    short_name: '',
    description: '',
    tags: [],
    kind: 'numeric',
    calculation: 'reported',
    config: { min: 0, max: 1 },
    composition: null,
    input_scorers: [],
    dependent_composite_count: 0,
    archived: false,
    current_version: 2,
    current_version_id: 'source-version',
    team: MOCK_DEFAULT_TEAM.id,
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_by: null,
    updated_at: null,
}

describe.each([false, true])('scorer scene duplication with Today navigation: %s', (todayRailNav) => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        window.POSTHOG_APP_CONTEXT!.resource_access_control = {
            ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
            llm_analytics: AccessControlLevel.Editor,
        }
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS], {
            [FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS]: true,
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayRailNav,
        })
        const emptyPage = { results: [], count: 0, next: null, previous: null }
        jest.mocked(llmAnalyticsScoreDefinitionsList).mockResolvedValue(emptyPage)
        jest.mocked(llmAnalyticsScoreDefinitionsVersionsList).mockResolvedValue({ ...emptyPage, next_cursor: null })
    })

    afterEach(cleanup)

    it.each(['reported', 'composite'] as const)(
        'copies and saves a %s scorer through the scene route',
        async (calculation) => {
            const definition: ScoreDefinitionApi =
                calculation === 'reported'
                    ? source
                    : {
                          ...source,
                          kind: 'boolean',
                          calculation,
                          config: { true_is_failure: false, true_label: 'Ready', false_label: 'Review' },
                          composition: {
                              expression: 'quality >= 0.8',
                              inputs: [{ alias: 'quality', scorer_version_id: 'input-version-1' }],
                          },
                          input_scorers: [
                              {
                                  alias: 'quality',
                                  definition_id: 'input-scorer',
                                  name: 'Quality input',
                                  kind: 'numeric',
                                  config: { min: 0, max: 1 },
                                  scorer_version_id: 'input-version-1',
                                  version: 1,
                                  latest_version_id: 'input-version-2',
                                  latest_version: 2,
                              },
                          ],
                      }
            jest.mocked(llmAnalyticsScoreDefinitionsRetrieve).mockResolvedValue(definition)
            jest.mocked(llmAnalyticsScoreDefinitionsCreate).mockResolvedValue({
                ...definition,
                id: 'copied-scorer',
                current_version: 1,
            })
            const params = { scorerId: 'new' }
            const searchParams = { duplicate: definition.id }
            router.actions.push(urls.aiObservabilityScorer('new'), searchParams)
            const SceneComponent = scene.component
            const { container } = render(
                <BindLogic logic={scorerLogic} props={scene.paramsToProps!({ params, searchParams, hashParams: {} })}>
                    <SceneComponent {...params} />
                </BindLogic>
            )

            await waitFor(() =>
                expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Answer quality copy')
            )
            if (calculation === 'composite') {
                expect((screen.getByLabelText('Formula') as HTMLTextAreaElement).value).toBe('quality >= 0.8')
            }
            fireEvent.click(container.querySelector('[data-attr="llma-scorer-save"]')!)

            await waitFor(() =>
                expect(llmAnalyticsScoreDefinitionsCreate).toHaveBeenCalledWith(
                    String(MOCK_DEFAULT_TEAM.id),
                    expect.objectContaining({
                        name: 'Answer quality copy',
                        kind: definition.kind,
                        config: definition.config,
                        ...(definition.composition ? { calculation, composition: definition.composition } : {}),
                    })
                )
            )
            await waitFor(() =>
                expect(router.values.location.pathname).toBe(
                    `/project/${MOCK_DEFAULT_TEAM.id}${urls.aiObservabilityScorers()}`
                )
            )
        }
    )
})
