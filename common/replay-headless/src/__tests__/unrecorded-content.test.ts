import type { Replayer } from 'posthog-js/rrweb'
import type { eventWithTime } from 'posthog-js/rrweb-types'

import { UNRECORDED_ATTRIBUTE, UnrecordedContentPlugin } from '../unrecorded-content'

// posthog-js/* ships ESM the test transform can't load; these mirror rrweb's enum values.
jest.mock('posthog-js/rrweb-types', () => ({
    EventType: { IncrementalSnapshot: 3 },
    IncrementalSource: { Mutation: 0, CanvasMutation: 9 },
}))

const NODE_ID = 7

function replayerWith(tagName: string, attributes: Record<string, string>, element: Element): Replayer {
    const meta = { type: 2, tagName, attributes, childNodes: [], id: NODE_ID }
    return {
        getMirror: () => ({ getMeta: () => meta, getNode: (id: number) => (id === NODE_ID ? element : null) }),
    } as unknown as Replayer
}

function build(tagName: string, attributes: Record<string, string>, events: eventWithTime[]): string | null {
    const element = document.createElement(tagName)
    UnrecordedContentPlugin(events).onBuild?.(element, {
        id: NODE_ID,
        replayer: replayerWith(tagName, attributes, element),
    })
    return element.getAttribute(UNRECORDED_ATTRIBUTE)
}

function attributeChange(attributes: Record<string, string | null>): eventWithTime {
    return {
        type: 3,
        timestamp: 2000,
        data: { source: 0, texts: [], removes: [], adds: [], attributes: [{ id: NODE_ID, attributes }] },
    } as unknown as eventWithTime
}

const drawn = {
    type: 3,
    timestamp: 2000,
    data: { source: 9, id: NODE_ID, type: 0, commands: [] },
} as unknown as eventWithTime

const imageSetLater = attributeChange({ rr_dataURL: 'data:image/png;base64,AA==' })

const iframePageRecorded = {
    type: 3,
    timestamp: 2000,
    data: {
        source: 0,
        texts: [],
        removes: [],
        attributes: [],
        adds: [{ parentId: NODE_ID, nextId: null, node: { type: 0, childNodes: [], id: 99 } }],
        isAttachIframe: true,
    },
} as unknown as eventWithTime

describe('UnrecordedContentPlugin', () => {
    it.each([
        ['a cross-origin iframe', 'iframe', { rr_src: 'https://embed.example.com/' }, [], 'embed'],
        ['a recorded iframe', 'iframe', {}, [], null],
        [
            'a cross-origin iframe whose page was recorded',
            'iframe',
            { rr_src: 'https://embed.example.com/' },
            [iframePageRecorded],
            null,
        ],
        ['a canvas with no pixels recorded', 'canvas', {}, [], 'canvas'],
        ['a canvas with recorded drawing', 'canvas', {}, [drawn], null],
        ['a canvas with a snapshot image', 'canvas', { rr_dataURL: 'data:image/png;base64,AA==' }, [], null],
        ['a canvas whose image arrives later', 'canvas', {}, [imageSetLater], null],
        ['a canvas whose image is removed', 'canvas', {}, [attributeChange({ rr_dataURL: null })], 'canvas'],
    ])('labels %s correctly', (_label, tagName, attributes, events, expected) => {
        expect(build(tagName, attributes, events)).toBe(expected)
    })

    it('labels an iframe whose cross-origin src arrives later', () => {
        const element = document.createElement('iframe')
        const change = attributeChange({ rr_src: 'https://embed.example.com/' })
        UnrecordedContentPlugin([change]).handler?.(change, false, { replayer: replayerWith('iframe', {}, element) })
        expect(element.getAttribute(UNRECORDED_ATTRIBUTE)).toBe('embed')
    })
})
