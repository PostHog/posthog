import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { globalSetupLogic } from './globalSetupLogic'
import { useSetupHighlight } from './useSetupHighlight'

describe('useSetupHighlight', () => {
    const SELECTOR = '[data-attr="quick-start-target"]'
    const PULSE_CLASS = 'setup-highlight-pulse'

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        render(<HighlightHost />)
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        document.body.innerHTML = ''
    })

    function HighlightHost(): JSX.Element {
        useSetupHighlight()
        return <div />
    }

    const addTarget = (): HTMLElement => {
        const element = document.createElement('button')
        element.setAttribute('data-attr', 'quick-start-target')
        document.body.append(element)
        return element
    }

    it('pulses the target on the route that asked for it', () => {
        const target = addTarget()

        act(() => globalSetupLogic.actions.setHighlight(SELECTOR, router.values.location.pathname))
        act(() => void jest.advanceTimersByTime(400))

        expect(target).toHaveClass(PULSE_CLASS)
    })

    // The reported bug: the poll outlived its route, so it pulsed the first matching element on
    // whatever page the user opened next. Many task selectors only match deeper inside an entity,
    // which is why the poll so often had nothing to match on the page it was meant for.
    it('does not pulse a matching element on a page opened later', () => {
        act(() => globalSetupLogic.actions.setHighlight(SELECTOR, urls.featureFlag('new')))
        act(() => void jest.advanceTimersByTime(400))

        act(() => router.actions.push(urls.insights()))
        const lateTarget = addTarget()
        act(() => void jest.advanceTimersByTime(2000))

        expect(lateTarget).not.toHaveClass(PULSE_CLASS)
    })
})
