import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
    })
    afterEach(() => {
        cleanup()
    })

    it('links Settings and the available Magic 8 ball to their scenes', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        render(<BusinessKnowledgeTabs activeTab="sources" />)

        expect(screen.getByText('Sources').closest('a')?.getAttribute('href')).toMatch(/\/business-knowledge$/)
        expect(screen.getByText('Magic 8 ball').closest('a')?.getAttribute('href')).toMatch(
            /\/business-knowledge\/magic-8-ball$/
        )
        expect(screen.getByText('Settings').closest('a')?.getAttribute('href')).toMatch(
            /\/business-knowledge\/settings$/
        )
    })

    it('does not show the Magic 8 ball outside the US cloud', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        preflightLogic.actions.loadPreflightSuccess({ region: Region.EU } as PreflightStatus)
        render(<BusinessKnowledgeTabs activeTab="sources" />)
        expect(screen.queryByText('Magic 8 ball')).not.toBeInTheDocument()
    })

    it('does not show the Magic 8 ball without decision enrollment', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(<BusinessKnowledgeTabs activeTab="sources" />)
        expect(screen.queryByText('Magic 8 ball')).not.toBeInTheDocument()
    })
})
