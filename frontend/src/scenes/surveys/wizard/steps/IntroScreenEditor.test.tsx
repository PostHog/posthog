import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

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

    it.each([
        ['an unset content type', undefined, 'html'],
        ['an html content type', 'html', 'html'],
        ['a text content type', 'text', 'text'],
    ] as const)('opens the description on the tab the SDK renders for %s', (_name, contentType, expectedTab) => {
        render(
            <IntroScreenEditor
                appearance={{ displayIntroScreen: true, introScreenDescriptionContentType: contentType }}
                onUpdate={jest.fn()}
                onToggle={jest.fn()}
            />
        )

        const activeTab = expectedTab === 'html' ? 'HTML' : 'Text'
        expect(screen.getByText(activeTab).closest('[role="tab"]')).toHaveAttribute('aria-selected', 'true')
    })

    it('lets an html intro switch its description to text', () => {
        const onUpdate = jest.fn()
        render(
            <IntroScreenEditor
                appearance={{ displayIntroScreen: true, introScreenDescriptionContentType: 'html' }}
                onUpdate={onUpdate}
                onToggle={jest.fn()}
            />
        )

        fireEvent.click(screen.getByText('Text'))

        expect(onUpdate).toHaveBeenCalledWith({ introScreenDescriptionContentType: 'text' })
    })
})
