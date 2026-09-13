import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'
import { PreflightStatus, Region } from '~/types'

import { LLMProvider } from './llmProviderKeysLogic'
import { LLMProviderResidencyNotice } from './LLMProviderResidencyNotice'

describe('LLMProviderResidencyNotice', () => {
    beforeEach(() => {
        initKeaTests()
        preflightLogic.mount()
    })

    afterEach(cleanup)

    const cases: [string, Region, LLMProvider, boolean][] = [
        ['EU project with a global endpoint provider', Region.EU, 'gemini', true],
        ['EU project with a customer endpoint provider', Region.EU, 'azure_openai', false],
        ['US project with a global endpoint provider', Region.US, 'gemini', false],
    ]

    test.each(cases)('%s', (_name, region, provider, expectedVisible) => {
        preflightLogic.actions.loadPreflightSuccess({ cloud: true, region } as PreflightStatus)

        render(<LLMProviderResidencyNotice provider={provider} />)

        const banner = screen.queryByText(/can be processed outside the EU/)
        if (expectedVisible) {
            expect(banner).toBeInTheDocument()
        } else {
            expect(banner).not.toBeInTheDocument()
        }
    })
})
