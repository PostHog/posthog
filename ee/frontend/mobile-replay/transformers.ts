import { EventType, fullSnapshotEvent, metaEvent } from '@rrweb/types'

import {
    fullSnapshotEvent as MobileFullSnapshotEvent,
    metaEvent as MobileMetaEvent,
    NodeType,
    serializedNodeWithId,
    wireframe,
    wireframeDiv,
    wireframeImage,
    wireframeRectangle,
    wireframeText,
} from './mobile.types'
import { makePositionStyles, makeStylesString, makeSvgBorder } from './wireframeStyle'

/**
 * generates a sequence of ids
 * from 100 to 9,999,999
 * the transformer reserves ids in the range 0 to 9,999,999
 * we reserve a range of ids because we need nodes to have stable ids across snapshots
 * in order for incremental snapshots to work
 * some mobile elements have to be wrapped in other elements in order to be styled correctly
 * which means the web version of a mobile replay will use ids that don't exist in the mobile replay,
 * and we need to ensure they don't clash
 * -----
 * id is typed as a number in rrweb
 * and there's a few places in their code where rrweb uses a check for `id === -1` to bail out of processing
 * so, it's safest to assume that id is expected to be a positive integer
 */
function* ids(): Generator<number> {
    let i = 100
    while (i < 9999999) {
        yield i++
    }
}
const idSequence = ids()

export const makeMetaEvent = (
    mobileMetaEvent: MobileMetaEvent & {
        timestamp: number
    }
): metaEvent & {
    timestamp: number
    delay?: number
} => ({
    type: EventType.Meta,
    data: {
        href: mobileMetaEvent.data.href || '', // the replay doesn't use the href, so we safely ignore any absence
        // mostly we need width and height in order to size the viewport
        width: mobileMetaEvent.data.width,
        height: mobileMetaEvent.data.height,
    },
    timestamp: mobileMetaEvent.timestamp,
})

function _isPositiveInteger(id: unknown): boolean {
    return typeof id === 'number' && id > 0 && id % 1 === 0
}

function makeDivElement(wireframe: wireframeDiv, children: serializedNodeWithId[]): serializedNodeWithId | null {
    const _id = _isPositiveInteger(wireframe.id) ? wireframe.id : idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe) + 'overflow:hidden;white-space:nowrap;',
        },
        id: _id,
        childNodes: children,
    }
}

function makeTextElement(wireframe: wireframeText, children: serializedNodeWithId[]): serializedNodeWithId | null {
    if (wireframe.type !== 'text') {
        console.error('Passed incorrect wireframe type to makeTextElement')
        return null
    }

    // because we might have to style the text, we always wrap it in a div
    // and apply styles to that
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe) + 'overflow:hidden;white-space:nowrap;',
        },
        id: idSequence.next().value,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: wireframe.text,
                id: wireframe.id,
            },
            ...children,
        ],
    }
}

function makeImageElement(wireframe: wireframeImage, children: serializedNodeWithId[]): serializedNodeWithId | null {
    const src = wireframe.base64
    if (!src.startsWith('data:image/')) {
        console.error('Expected base64 to start with data:image/')
        return null
    }

    return {
        type: NodeType.Element,
        tagName: 'img',
        attributes: {
            src: src,
            width: wireframe.width,
            height: wireframe.height,
            style: makeStylesString(wireframe),
        },
        id: wireframe.id,
        childNodes: children,
    }
}

function makeRectangleElement(
    wireframe: wireframeRectangle,
    children: serializedNodeWithId[]
): serializedNodeWithId | null {
    return {
        type: NodeType.Element,
        tagName: 'svg',
        attributes: {
            style: makePositionStyles(wireframe),
            viewBox: `0 0 ${wireframe.width} ${wireframe.height}`,
        },
        id: wireframe.id,
        childNodes: [
            {
                type: NodeType.Element,
                tagName: 'rect',
                attributes: {
                    x: 0,
                    y: 0,
                    width: wireframe.width,
                    height: wireframe.height,
                    fill: wireframe.style?.backgroundColor || 'transparent',
                    ...makeSvgBorder(wireframe.style),
                },
                id: idSequence.next().value,
                childNodes: children,
            },
        ],
    }
}

function chooseConverter<T extends wireframe>(
    wireframe: T
): (wireframe: T, children: serializedNodeWithId[]) => serializedNodeWithId | null {
    // in theory type is always present
    // but since this is coming over the wire we can't really be sure
    // and so we default to div
    const converterType = wireframe.type || 'div'
    switch (converterType) {
        case 'text':
            return makeTextElement as unknown as (
                wireframe: T,
                children: serializedNodeWithId[]
            ) => serializedNodeWithId | null
        case 'image':
            return makeImageElement as unknown as (
                wireframe: T,
                children: serializedNodeWithId[]
            ) => serializedNodeWithId | null
        case 'rectangle':
            return makeRectangleElement as unknown as (
                wireframe: T,
                children: serializedNodeWithId[]
            ) => serializedNodeWithId | null
        case 'div':
            return makeDivElement as unknown as (
                wireframe: T,
                children: serializedNodeWithId[]
            ) => serializedNodeWithId | null
    }
}

function convertWireframesFor(wireframes: wireframe[] | undefined): serializedNodeWithId[] {
    if (!wireframes) {
        return []
    }

    return wireframes.reduce((acc, wireframe) => {
        const children = convertWireframesFor(wireframe.childWireframes)
        const converter = chooseConverter(wireframe)
        if (!converter) {
            console.error(`No converter for wireframe type ${wireframe.type}`)
            return acc
        }
        const convertedEl = converter(wireframe, children)
        if (convertedEl !== null) {
            acc.push(convertedEl)
        }
        return acc
    }, [] as serializedNodeWithId[])
}

export const makeFullEvent = (
    mobileEvent: MobileFullSnapshotEvent & {
        timestamp: number
        delay?: number
    }
): fullSnapshotEvent & {
    timestamp: number
    delay?: number
} => {
    if (!('wireframes' in mobileEvent.data)) {
        return mobileEvent as unknown as fullSnapshotEvent & {
            timestamp: number
            delay?: number
        }
    }

    return {
        type: EventType.FullSnapshot,
        timestamp: mobileEvent.timestamp,
        data: {
            node: {
                type: NodeType.Document,
                childNodes: [
                    {
                        type: NodeType.DocumentType,
                        name: 'html',
                        publicId: '',
                        systemId: '',
                        id: 2,
                    },
                    {
                        type: NodeType.Element,
                        tagName: 'html',
                        attributes: {},
                        id: 3,
                        childNodes: [
                            {
                                type: NodeType.Element,
                                tagName: 'head',
                                attributes: {},
                                id: 4,
                                childNodes: [],
                            },
                            {
                                type: NodeType.Element,
                                tagName: 'body',
                                attributes: {},
                                id: 5,
                                childNodes: [
                                    {
                                        type: NodeType.Element,
                                        tagName: 'div',
                                        attributes: {},
                                        id: idSequence.next().value,
                                        childNodes: convertWireframesFor(mobileEvent.data.wireframes),
                                    },
                                ],
                            },
                        ],
                    },
                ],
                id: 1,
            },
            initialOffset: {
                top: 0,
                left: 0,
            },
        },
    }
}
