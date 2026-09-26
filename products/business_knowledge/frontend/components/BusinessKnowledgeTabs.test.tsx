import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { BusinessKnowledgeTabs } from './BusinessKnowledgeTabs'

describe('BusinessKnowledgeTabs', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
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

    it('does not show the Magic 8 ball without decision enrollment', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(<BusinessKnowledgeTabs activeTab="sources" />)
        expect(screen.queryByText('Magic 8 ball')).not.toBeInTheDocument()
    })
})
