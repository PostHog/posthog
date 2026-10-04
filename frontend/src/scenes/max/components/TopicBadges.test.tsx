import { cleanup, fireEvent, render } from '@testing-library/react'

import { HOMEPAGE_SUGGESTION_TOPICS } from 'scenes/max/suggestionTopics'

import { initKeaTests } from '~/test/init'

import { TopicBadges } from './TopicBadges'

describe('TopicBadges', () => {
    const [first, second] = HOMEPAGE_SUGGESTION_TOPICS

    function renderBadges(selectedKey: string | null): jest.Mock {
        const onSelect = jest.fn()
        render(<TopicBadges topics={HOMEPAGE_SUGGESTION_TOPICS} selectedKey={selectedKey} onSelect={onSelect} />)
        return onSelect
    }

    const badge = (key: string): HTMLElement =>
        document.querySelector<HTMLElement>(`[data-attr="capability-badge-${key}"]`) as HTMLElement

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it.each([
        ['an unselected badge selects it', null, first.key, [first.key]],
        ['another badge switches to it', first.key, second.key, [second.key]],
        ['the selected badge again does nothing', first.key, first.key, null],
        ['clear resets the topic', first.key, 'clear', [null]],
    ])('clicking %s', (_, selectedKey, clicked, expectedCall) => {
        const onSelect = renderBadges(selectedKey)

        fireEvent.click(badge(clicked))

        if (expectedCall) {
            expect(onSelect).toHaveBeenCalledWith(...expectedCall)
        } else {
            expect(onSelect).not.toHaveBeenCalled()
        }
    })
})
