import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { initKeaTests } from '~/test/init'
import { Region } from '~/types'
import type { PreflightStatus } from '~/types'

import { BusinessKnowledgeTabs } from './BusinessKnowledgeTabs'

describe('BusinessKnowledgeTabs', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ region: Region.US } as PreflightStatus)
        organizationLogic.actions.loadCurrentOrganizationSuccess(MOCK_DEFAULT_ORGANIZATION)
    })
    afterEach(() => {
        cleanup()
    })

    it('links Settings and the available Magic 8 ball to their scenes', () => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true,
            [FEATURE_FLAGS.BUSINESS_KNOWLEDGE_MAGIC_EIGHT_BALL]: true,
        })
        render(<BusinessKnowledgeTabs activeTab="sources" />)

        expect(screen.getByText('Sources').closest('a')?.getAttribute('href')).toMatch(/\/business-knowledge$/)
        expect(screen.getByText('Magic 8 ball').closest('a')?.getAttribute('href')).toMatch(
            /\/business-knowledge\/magic-8-ball$/
        )
        expect(screen.getByText('Settings').closest('a')?.getAttribute('href')).toMatch(
            /\/business-knowledge\/settings$/
        )
    })

    it.each<{
        name: string
        flags: Record<string, boolean>
        setupOrg?: () => void
        setupPreflight?: () => void
    }>([
        {
            name: 'outside the US cloud',
            flags: {
                [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true,
                [FEATURE_FLAGS.BUSINESS_KNOWLEDGE_MAGIC_EIGHT_BALL]: true,
            },
            setupPreflight: () => preflightLogic.actions.loadPreflightSuccess({ region: Region.EU } as PreflightStatus),
        },
        {
            name: 'without AI processing approval',
            flags: {
                [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true,
                [FEATURE_FLAGS.BUSINESS_KNOWLEDGE_MAGIC_EIGHT_BALL]: true,
            },
            setupOrg: () =>
                organizationLogic.actions.loadCurrentOrganizationSuccess({
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: false,
                }),
        },
        {
            name: 'without decision enrollment',
            flags: { [FEATURE_FLAGS.BUSINESS_KNOWLEDGE_MAGIC_EIGHT_BALL]: true },
        },
        {
            name: 'when its rollout flag is off',
            flags: { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true },
        },
    ])('does not show the Magic 8 ball $name', ({ flags, setupOrg, setupPreflight }) => {
        featureFlagLogic.actions.setFeatureFlags([], flags)
        setupOrg?.()
        setupPreflight?.()
        render(<BusinessKnowledgeTabs activeTab="sources" />)
        expect(screen.queryByText('Magic 8 ball')).not.toBeInTheDocument()
    })
})
