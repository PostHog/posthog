import { toolbarLogger } from '~/toolbar/toolbarLogger'
import * as toolbarPosthogJS from '~/toolbar/toolbarPosthogJS'
import { ActionStepForm } from '~/toolbar/types'

import { getElementForStep, joinWithUiHost, slashDotDataAttrUnescape } from './utils'

jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    captureToolbarException: jest.fn(),
    toolbarPosthogJS: {
        has_opted_in_capturing: () => false,
        config: { api_host: '', token: '' },
    },
}))

describe('utils', () => {
    describe('joinWithUiHost', () => {
        const testCases: Array<{ uiHost: string; path: string; expected: string }> = [
            {
                uiHost: 'https://us.posthog.com',
                path: '/settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com/',
                path: '/settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com///',
                path: 'settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com',
                path: 'settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com/',
                path: '///settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com',
                path: `${'/settings/project'}#heatmaps`,
                expected: 'https://us.posthog.com/settings/project#heatmaps',
            },
            { uiHost: 'https://us.posthog.com', path: '?a=1', expected: 'https://us.posthog.com/?a=1' },
            { uiHost: 'https://us.posthog.com', path: '#hash', expected: 'https://us.posthog.com/#hash' },
            { uiHost: 'https://us.posthog.com', path: 'https://example.com/x', expected: 'https://example.com/x' },
            { uiHost: 'https://us.posthog.com', path: '//example.com/x', expected: '//example.com/x' },
            { uiHost: '', path: '/settings/project', expected: '/settings/project' },
        ]

        testCases.forEach(({ uiHost, path, expected }) => {
            it(`joins "${uiHost}" + "${path}"`, () => {
                expect(joinWithUiHost(uiHost, path)).toBe(expected)
            })
        })
    })

    describe('slashDotDataAttrUnescape', () => {
        const testCases = [
            {
                input: 'div[data-attr="test"]',
                expected: 'div[data-attr="test"]',
            },
            {
                input: 'div[data-attr="test\\."]',
                expected: 'div[data-attr="test."]',
            },
            {
                input: 'div[data-something="test\\.test\\.test"]',
                expected: 'div[data-something="test.test.test"]',
            },
            {
                input: '.tomato div[data-something="test\\.test\\.test"]',
                expected: '.tomato div[data-something="test.test.test"]',
            },
            {
                input: '\\.tomato div[data-something="test\\.test\\.test"]',
                expected: '.tomato div[data-something="test.test.test"]',
            },
        ]
        testCases.forEach(({ input, expected }) => {
            it(`should unescape "${input}" to "${expected}"`, () => {
                const result = slashDotDataAttrUnescape(input)
                expect(result).toBe(expected)
            })
        })
    })

    describe('getElementForStep', () => {
        let warnSpy: jest.SpyInstance
        let errorSpy: jest.SpyInstance

        beforeEach(() => {
            warnSpy = jest.spyOn(toolbarLogger, 'warn').mockImplementation(() => {})
            errorSpy = jest.spyOn(toolbarLogger, 'error').mockImplementation(() => {})
            ;(toolbarPosthogJS.captureToolbarException as jest.Mock).mockClear()
        })

        afterEach(() => {
            warnSpy.mockRestore()
            errorSpy.mockRestore()
        })

        it('logs a warning but does not capture an exception for an invalid selector', () => {
            // Bare '.' is a syntax error in querySelector — stand-in for malformed user-saved
            // selectors like '.foo > . .bar' that throw in real browsers.
            const result = getElementForStep({
                selector: '.',
                selector_selected: true,
            } as ActionStepForm)

            expect(result).toBeNull()
            expect(warnSpy).toHaveBeenCalledWith(
                'element_step_selector',
                'Invalid selector',
                expect.objectContaining({ selector: '.' })
            )
            expect(errorSpy).not.toHaveBeenCalled()
            expect(toolbarPosthogJS.captureToolbarException).not.toHaveBeenCalled()
        })
    })
})
