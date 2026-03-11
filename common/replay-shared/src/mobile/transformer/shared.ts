import { NodeType, serializedNodeWithId, wireframe } from '../mobile.types'
import { ConversionContext, ConversionResult } from './types'
import { makeStylesString } from './wireframeStyle'

export const PLACEHOLDER_SVG_DATA_IMAGE_URL =
    'url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg==")'

export const BACKGROUND = '#f3f4ef'
export const FOREGROUND = '#35373e'

export const NAVIGATION_BAR_ID = 8
export const KEYBOARD_ID = 10
export const STATUS_BAR_ID = 12

export function _isPositiveInteger(id: unknown): id is number {
    return typeof id === 'number' && id > 0 && id % 1 === 0
}

export function makePlaceholderElement(
    wireframe: wireframe,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    const txt = 'label' in wireframe && wireframe.label ? wireframe.label : wireframe.type || 'PLACEHOLDER'
    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: makeStylesString(wireframe, {
                    verticalAlign: 'center',
                    horizontalAlign: 'center',
                    backgroundColor: wireframe.style?.backgroundColor || BACKGROUND,
                    color: wireframe.style?.color || FOREGROUND,
                    backgroundImage: PLACEHOLDER_SVG_DATA_IMAGE_URL,
                    backgroundSize: 'auto',
                    backgroundRepeat: 'unset',
                    ...context.styleOverride,
                }),
                'data-rrweb-id': wireframe.id,
            },
            id: wireframe.id,
            childNodes: [
                {
                    type: NodeType.Text,
                    id: context.idSequence.next().value,
                    textContent: txt,
                },
                ...children,
            ],
        },
        context,
    }
}
