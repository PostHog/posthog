import '@testing-library/jest-dom'

import { InsightShortId } from '~/types'

import { INSIGHT_CARD_KEY_ATTR, insightCardCaptureTarget } from './insightCardImageCapture'

describe('insightCardCaptureTarget', () => {
    const insight = { short_id: 'abc123' as InsightShortId, name: 'Weekly signups', derived_name: null }

    function renderCards(keys: string[]): void {
        document.body.innerHTML = keys.map((key) => `<div ${INSIGHT_CARD_KEY_ATTR}="${key}">${key}</div>`).join('')
    }

    it('finds the tile it was built for, not the first card on the page', () => {
        renderCards(['tile-1', 'tile-2'])

        const target = insightCardCaptureTarget(insight, { id: 2 })

        expect(document.querySelector(target.selector)).toHaveTextContent('tile-2')
    })

    it('falls back to the insight when the card is not a dashboard tile', () => {
        renderCards(['insight-abc123'])

        const target = insightCardCaptureTarget(insight)

        expect(document.querySelector(target.selector)).toHaveTextContent('insight-abc123')
    })

    it('names the file after the insight', () => {
        expect(insightCardCaptureTarget(insight).name).toBe('Weekly signups')
        expect(insightCardCaptureTarget({ ...insight, name: '', derived_name: 'Pageview count' }).name).toBe(
            'Pageview count'
        )
    })
})
