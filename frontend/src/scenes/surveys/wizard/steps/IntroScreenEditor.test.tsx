import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { SurveyAppearance } from '~/types'

import { IntroScreenEditor } from './IntroScreenEditor'

describe('IntroScreenEditor', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['an enabled intro with no content', { displayIntroScreen: true }, true],
        ['an enabled intro with a header', { displayIntroScreen: true, introScreenHeader: 'Welcome' }, false],
        ['an enabled intro with a description', { displayIntroScreen: true, introScreenDescription: 'Hi' }, false],
        ['a disabled intro', { displayIntroScreen: false }, false],
    ] as [string, SurveyAppearance, boolean][])(
        'warns that the intro will not show for %s',
        (_name, appearance, warns) => {
            render(<IntroScreenEditor appearance={appearance} onUpdate={jest.fn()} onToggle={jest.fn()} />)

            const warning = screen.queryByText("The intro screen won't show until it has a header or a description.")
            expect(!!warning).toBe(warns)
        }
    )
})
