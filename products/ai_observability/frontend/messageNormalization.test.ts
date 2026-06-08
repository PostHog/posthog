import posthog, { JsonType } from 'posthog-js'

import { CompatMessage } from './types'

const mockRecipeNormalizeMessage = jest.fn()
const mockRecipeNormalizeMessages = jest.fn()

jest.mock('./normalizer', () => ({
    RecipeNormalizer: jest.fn().mockImplementation(() => ({
        normalizeMessage: mockRecipeNormalizeMessage,
        normalizeMessages: mockRecipeNormalizeMessages,
    })),
}))

jest.mock('./utils', () => ({
    normalizeMessage: jest.fn(),
    normalizeMessages: jest.fn(),
}))

import { normalizeMessage, normalizeMessages } from './messageNormalization'
import { normalizeMessage as legacyNormalizeMessage, normalizeMessages as legacyNormalizeMessages } from './utils'

const LEGACY: CompatMessage[] = [{ role: 'user', content: 'legacy' }]
const RECIPE: CompatMessage[] = [{ role: 'user', content: 'recipe' }]

const legacy = jest.mocked(legacyNormalizeMessages)
const legacyOne = jest.mocked(legacyNormalizeMessage)
const getFeatureFlagResult = jest.mocked(posthog.getFeatureFlagResult)
const capture = jest.mocked(posthog.capture)

function mockFlag(enabled: boolean, payload?: JsonType): void {
    getFeatureFlagResult.mockReturnValue({ key: 'recipe-normalizer', enabled, variant: undefined, payload })
}

beforeEach(() => {
    jest.clearAllMocks()
    legacy.mockReturnValue(LEGACY)
    legacyOne.mockReturnValue(LEGACY)
    mockRecipeNormalizeMessages.mockReturnValue(RECIPE)
    mockRecipeNormalizeMessage.mockReturnValue(RECIPE)
})

describe('messageNormalization — switch (unsampled) path', () => {
    beforeEach(() => jest.spyOn(Math, 'random').mockReturnValue(0.5))

    it('runs only the legacy implementation when the flag is off', () => {
        mockFlag(false)
        expect(normalizeMessages({ role: 'user' }, 'user')).toBe(LEGACY)
        expect(mockRecipeNormalizeMessages).not.toHaveBeenCalled()
    })

    it('runs only the recipe implementation when the flag is on', () => {
        mockFlag(true)
        expect(normalizeMessages({ role: 'user' }, 'user')).toBe(RECIPE)
        expect(legacy).not.toHaveBeenCalled()
    })

    it('falls back to legacy and reports when the recipe implementation throws', () => {
        mockFlag(true)
        mockRecipeNormalizeMessages.mockImplementation(() => {
            throw new Error('no recipe matched')
        })
        expect(normalizeMessages({ role: 'user' }, 'user')).toBe(LEGACY)
        expect(capture).toHaveBeenCalledWith('llma recipe normalization fell back', {
            error: 'no recipe matched',
        })
    })

    it('does not emit a timing event off the sampled path', () => {
        mockFlag(false)
        normalizeMessages({ role: 'user' }, 'user')
        expect(capture).not.toHaveBeenCalledWith('llma normalization timed', expect.anything())
    })

    it('honors a higher sample_rate from the flag payload to force the sampled path', () => {
        mockFlag(true, { sample_rate: 1 })
        normalizeMessages({ role: 'user' }, 'user')
        expect(capture).toHaveBeenCalledWith('llma normalization timed', expect.anything())
    })
})

describe('messageNormalization — shadow (sampled) path', () => {
    beforeEach(() => jest.spyOn(Math, 'random').mockReturnValue(0))

    it('runs both implementations and captures a timing comparison', () => {
        mockFlag(false)
        normalizeMessages({ role: 'user' }, 'user', [{ name: 'search' }])
        expect(legacy).toHaveBeenCalledTimes(1)
        expect(mockRecipeNormalizeMessages).toHaveBeenCalledTimes(1)
        expect(capture).toHaveBeenCalledWith(
            'llma normalization timed',
            expect.objectContaining({
                op: 'normalizeMessages',
                active_implementation: 'legacy',
                default_role: 'user',
                has_tools: true,
                recipe_errored: false,
                outputs_match: false,
                message_count: 1,
                legacy_duration_ms: expect.any(Number),
                recipe_duration_ms: expect.any(Number),
            })
        )
    })

    it('reports outputs_match true when both implementations agree', () => {
        mockFlag(true)
        mockRecipeNormalizeMessages.mockReturnValue([{ role: 'user', content: 'legacy' }])
        normalizeMessages({ role: 'user' }, 'user')
        expect(capture).toHaveBeenCalledWith(
            'llma normalization timed',
            expect.objectContaining({ outputs_match: true })
        )
    })

    it('returns the flag-selected recipe result while still timing legacy', () => {
        mockFlag(true)
        expect(normalizeMessages({ role: 'user' }, 'user')).toBe(RECIPE)
    })

    it('records recipe_errored and returns legacy when the recipe throws', () => {
        mockFlag(true)
        mockRecipeNormalizeMessages.mockImplementation(() => {
            throw new Error('boom')
        })
        expect(normalizeMessages({ role: 'user' }, 'user')).toBe(LEGACY)
        expect(capture).toHaveBeenCalledWith(
            'llma normalization timed',
            expect.objectContaining({ recipe_errored: true, recipe_duration_ms: null, outputs_match: null })
        )
    })

    it('tags the singular normalizeMessage path with its op', () => {
        mockFlag(false)
        normalizeMessage({ role: 'user' }, 'user')
        expect(capture).toHaveBeenCalledWith(
            'llma normalization timed',
            expect.objectContaining({ op: 'normalizeMessage' })
        )
    })

    it('honors a lower sample_rate from the flag payload to suppress timing', () => {
        mockFlag(true, { sample_rate: 0 })
        normalizeMessages({ role: 'user' }, 'user')
        expect(capture).not.toHaveBeenCalledWith('llma normalization timed', expect.anything())
    })
})
