import { cleanup, render, screen } from '@testing-library/react'

import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SuggestionModal } from './SuggestionModal'

const suggestion = (overrides: Partial<Suggestion> = {}): Suggestion =>
    ({
        id: 'fix_conversion_goal:cg_ghost',
        kind: 'fix_conversion_goal',
        source: 'deterministic',
        severity: 'error',
        title: "Remove or repoint the 'Ghost action (broken)' conversion goal",
        evidence: 'Action 999999 does not exist or is deleted.',
        unlocks: [],
        apply: { op: 'delete_conversion_goal', conversion_goal_id: 'cg_ghost' },
        also_recommended: [],
        safe_to_batch: false,
        rank_score: 10,
        integration: null,
        deep_link: null,
        docs_url: null,
        spend_at_risk: 0,
        event_volume: 0,
        ...overrides,
    }) as Suggestion

function renderModal(item: Suggestion): void {
    render(
        <SuggestionModal
            suggestion={item}
            batch={[]}
            isApplying={false}
            onClose={() => {}}
            onConfirm={() => {}}
            onConfirmBatch={() => {}}
        />
    )
}

describe('SuggestionModal', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': () => [200, {}],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('says Remove rather than leaving a strikethrough to carry the meaning', () => {
        renderModal(suggestion())

        // A minus glyph and struck-through text were the entire signal that a
        // destructive change was about to be approved.
        expect(screen.getByText('Remove')).toBeTruthy()
    })

    it('names the act on the confirm button', () => {
        renderModal(suggestion())

        // "Apply change" on a button that deletes a conversion goal is accurate and
        // useless.
        expect(screen.getByText('Remove goal')).toBeTruthy()
        expect(screen.queryByText('Apply change')).toBeNull()
    })

    it('keeps the generic label for an additive config edit', () => {
        renderModal(
            suggestion({
                apply: { op: 'add_custom_source_mapping', integration: 'MetaAds', raw_utm_source: 'fb-ads' },
            })
        )

        expect(screen.getByText('Apply change')).toBeTruthy()
        expect(screen.getByText('Add')).toBeTruthy()
    })
})
