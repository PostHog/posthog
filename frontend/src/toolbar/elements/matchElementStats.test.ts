import { ElementsEventType } from '~/toolbar/types'
import { TOOLBAR_EXTENSION_ID } from '~/toolbar/utils'

import { matchElementStatsToElements } from './matchElementStats'

function clickEvent(type: ElementsEventType['type'], count: number): ElementsEventType {
    return {
        count,
        hash: `${type}-hash`,
        type,
        elements: [{ tag_name: 'button', attributes: { 'attr__data-attr': 'signup' } }],
    }
}

describe('matchElementStatsToElements', () => {
    let originalCheckVisibility: typeof HTMLElement.prototype.checkVisibility

    beforeEach(() => {
        // jsdom has no layout, so every element would count as hidden.
        originalCheckVisibility = HTMLElement.prototype.checkVisibility
        HTMLElement.prototype.checkVisibility = () => true
        document.body.innerHTML = '<main><button data-attr="signup">Sign up</button></main>'
    })

    afterEach(() => {
        HTMLElement.prototype.checkVisibility = originalCheckVisibility
        document.body.innerHTML = ''
    })

    it('ignores the extension overlay and sums click types per page element', () => {
        const overlayHost = document.createElement('div')
        overlayHost.id = TOOLBAR_EXTENSION_ID
        overlayHost.attachShadow({ mode: 'open' }).innerHTML = '<button data-attr="signup">Sign up</button>'
        document.body.appendChild(overlayHost)

        const matched = matchElementStatsToElements([clickEvent('$autocapture', 3), clickEvent('$rageclick', 2)], {
            dataAttributes: ['data-attr'],
        })

        expect(matched).toHaveLength(1)
        expect(matched[0].element).toBe(document.querySelector('main button'))
        expect(matched[0]).toMatchObject({ count: 5, clickCount: 3, rageclickCount: 2, deadclickCount: 0, position: 1 })
    })
})
