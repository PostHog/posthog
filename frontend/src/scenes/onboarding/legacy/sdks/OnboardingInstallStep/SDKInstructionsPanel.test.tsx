import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { SDKKey, SDKTag } from '~/types'

import { SDKInstructionsPanel } from './SDKInstructionsPanel'

describe('SDKInstructionsPanel', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => cleanup())

    // An SDK can reach this panel without an entry in the caller's map, for example through the
    // ?sdk= URL parameter, which matches against every SDK rather than the installable ones. That
    // used to render a spinner in an empty modal with nothing to click.
    it('offers the docs when no instructions match the SDK', () => {
        render(
            <SDKInstructionsPanel
                sdk={{
                    name: 'Elixir',
                    key: SDKKey.ELIXIR,
                    tags: [SDKTag.SERVER],
                    image: '',
                    docsLink: 'https://posthog.com/docs/libraries/elixir',
                }}
                sdkInstructionMap={{}}
                adblockResult="ok"
                onBack={jest.fn()}
                hideInstallationCheck
            />
        )

        expect(screen.getByText('Install Elixir')).toBeInTheDocument()
        expect(screen.getByText('Read the install docs')).toBeInTheDocument()
    })
})
