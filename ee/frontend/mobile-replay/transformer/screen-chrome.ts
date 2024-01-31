import { NodeType, serializedNodeWithId, wireframeNavigationBar, wireframeStatusBar } from '../mobile.types'
import { isLight } from './colors'
import { NAVIGATION_BAR_ID, STATUS_BAR_ID } from './transformers'
import { ConversionContext, ConversionResult } from './types'
import { asStyleString, makeStylesString } from './wireframeStyle'

function spacerDiv(idSequence: Generator<number>): serializedNodeWithId {
    const spacerId = idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: 'width: 5px;',
            'data-rrweb-id': spacerId,
        },
        id: spacerId,
        childNodes: [],
    }
}

function makeFakeNavButton(icon: string, context: ConversionContext): serializedNodeWithId {
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {},
        id: context.idSequence.next().value,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: icon,
                id: context.idSequence.next().value,
            },
        ],
    }
}

export function makeNavigationBar(
    wireframe: wireframeNavigationBar,
    _children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    const _id = wireframe.id || NAVIGATION_BAR_ID

    const backArrowTriangle = makeFakeNavButton('◀', context)
    const homeCircle = makeFakeNavButton('⚪', context)
    const screenButton = makeFakeNavButton('⬜️', context)

    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: asStyleString([
                    makeStylesString(wireframe),
                    'display:flex',
                    'flex-direction:row',
                    'align-items:center',
                    'justify-content:space-around',
                    'color:white',
                ]),
                'data-rrweb-id': _id,
            },
            id: _id,
            childNodes: [backArrowTriangle, homeCircle, screenButton],
        },
        context,
    }
}

/**
 * tricky: we need to accept children because that's the interface of converters, but we don't use them
 */
export function makeStatusBar(
    wireframe: wireframeStatusBar,
    _children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> {
    const clockId = context.idSequence.next().value
    // convert the wireframe timestamp to a date time, then get just the hour and minute of the time from that
    const clockTime = context.timestamp
        ? new Date(context.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : ''

    const clockFontColor = isLight(wireframe.style?.backgroundColor || '#ffffff') ? 'black' : 'white'

    const clock: serializedNodeWithId = {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            'data-rrweb-id': clockId,
        },
        id: clockId,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: clockTime,
                id: context.idSequence.next().value,
            },
        ],
    }

    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: asStyleString([
                    makeStylesString(wireframe, { color: clockFontColor }),
                    'display:flex',
                    'flex-direction:row',
                    'align-items:center',
                ]),
                'data-rrweb-id': STATUS_BAR_ID,
            },
            id: STATUS_BAR_ID,
            childNodes: [spacerDiv(context.idSequence), clock],
        },
        context,
    }
}
