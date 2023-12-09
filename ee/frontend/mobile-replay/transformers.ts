import { EventType, fullSnapshotEvent, incrementalSnapshotEvent, metaEvent } from '@rrweb/types'

import {
    attributes,
    elementNode,
    fullSnapshotEvent as MobileFullSnapshotEvent,
    incrementalSnapshotEvent as MobileIncrementalSnapshotEvent,
    metaEvent as MobileMetaEvent,
    MobileNodeType,
    NodeType,
    serializedNodeWithId,
    textNode,
    wireframe,
    wireframeButton,
    wireframeDiv,
    wireframeImage,
    wireframeInputComponent,
    wireframeProgress,
    wireframeRadioGroup,
    wireframeRectangle,
    wireframeSelect,
    wireframeText,
    wireframeToggle,
} from './mobile.types'
import {
    makeBodyStyles,
    makeDeterminateProgressStyles,
    makeHTMLStyles,
    makeIndeterminateProgressStyles,
    makeMinimalStyles,
    makePositionStyles,
    makeStylesString,
    makeSvgBorder,
} from './wireframeStyle'

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

// TODO this is shared for the lifetime of the page, so a very, very long-lived session could exhaust the ids
const idSequence = ids()

const BODY_ID = 5

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

function _isPositiveInteger(id: unknown): id is number {
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

function makeWebViewElement(wireframe: wireframe, children: serializedNodeWithId[]): serializedNodeWithId | null {
    return makePlaceholderElement(wireframe, children)
}

function makePlaceholderElement(wireframe: wireframe, children: serializedNodeWithId[]): serializedNodeWithId | null {
    // <svg width="200" height="200">
    //  <rect width="100%" height="100%" fill="grey"/>
    //  <text fill="white" font-size="30" x="50%" y="50%" dominant-baseline="middle" text-anchor="middle">
    // Keyboard
    //  </text>
    // </svg>
    const txt = 'label' in wireframe && wireframe.label ? wireframe.label : wireframe.type || 'PLACEHOLDER'
    return {
        type: NodeType.Element,
        tagName: 'svg',
        attributes: {
            width: wireframe.width,
            height: wireframe.height,
            style: makeStylesString(wireframe),
        },
        id: wireframe.id,
        childNodes: [
            {
                type: NodeType.Element,
                tagName: 'rect',
                attributes: {
                    width: wireframe.width,
                    height: wireframe.height,
                    style: makeStylesString(wireframe),
                    fill: wireframe.style?.backgroundColor || 'grey',
                },
                id: idSequence.next().value,
                childNodes: [],
            },
            {
                type: NodeType.Element,
                tagName: 'text',
                attributes: {
                    fill: wireframe.style?.color || 'white',
                    'font-size': '30',
                    x: '50%',
                    y: '50%',
                    'dominant-baseline': 'middle',
                    'text-anchor': 'middle',
                },
                id: idSequence.next().value,
                childNodes: [
                    {
                        type: NodeType.Text,
                        textContent: txt,
                        id: idSequence.next().value,
                    },
                ],
            },
            ...children,
        ],
    }
}

function makeImageElement(wireframe: wireframeImage, children: serializedNodeWithId[]): serializedNodeWithId | null {
    if (!wireframe.base64) {
        return makePlaceholderElement(wireframe, children)
    }
    let src = wireframe.base64
    if (!src.startsWith('data:image/')) {
        src = 'data:image/png;base64,' + src
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

function inputAttributes<T extends wireframeInputComponent>(wireframe: T): attributes {
    const attributes = {
        style: makeStylesString(wireframe),
        type: wireframe.inputType,
        ...(wireframe.disabled ? { disabled: wireframe.disabled } : {}),
    }

    switch (wireframe.inputType) {
        case 'checkbox':
            return {
                ...attributes,
                style: null, // checkboxes are styled by being combined with a label
                ...(wireframe.checked ? { checked: wireframe.checked } : {}),
            }
        case 'toggle':
            return {
                ...attributes,
                style: null, // toggle are styled by being combined with a label
                ...(wireframe.checked ? { checked: wireframe.checked } : {}),
            }
        case 'radio':
            return {
                ...attributes,
                style: null, // radio buttons are styled by being combined with a label
                ...(wireframe.checked ? { checked: wireframe.checked } : {}),
                // radio value defaults to the string "on" if not specified
                // we're not really submitting the form, so it doesn't matter 🤞
                // radio name is used to correctly uncheck values when one is checked
                // mobile doesn't really have it, and we will be checking based on snapshots,
                // so we can ignore it for now
            }
        case 'button':
            return {
                ...attributes,
            }
        case 'text_area':
            return {
                ...attributes,
                value: wireframe.value || '',
            }
        case 'progress':
            return {
                ...attributes,
                // indeterminate when omitted
                value: wireframe.value || null,
                // defaults to 1 when omitted
                max: wireframe.max || null,
                type: null, // progress has no type attribute
            }
        default:
            return {
                ...attributes,
                value: wireframe.value || '',
            }
    }
}

function makeButtonElement(wireframe: wireframeButton, children: serializedNodeWithId[]): serializedNodeWithId | null {
    const buttonText: textNode | null = wireframe.value
        ? {
              type: NodeType.Text,
              textContent: wireframe.value,
          }
        : null

    return {
        type: NodeType.Element,
        tagName: 'button',
        attributes: inputAttributes(wireframe),
        id: wireframe.id,
        childNodes: buttonText ? [{ ...buttonText, id: idSequence.next().value }, ...children] : children,
    }
}

function makeSelectOptionElement(option: string, selected: boolean): serializedNodeWithId {
    return {
        type: NodeType.Element,
        tagName: 'option',
        attributes: {
            ...(selected ? { selected: selected } : {}),
        },
        id: idSequence.next().value,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: option,
                id: idSequence.next().value,
            },
        ],
    }
}

function makeSelectElement(wireframe: wireframeSelect, children: serializedNodeWithId[]): serializedNodeWithId | null {
    return {
        type: NodeType.Element,
        tagName: 'select',
        attributes: inputAttributes(wireframe),
        id: wireframe.id,
        childNodes: [
            ...(wireframe.options?.map((option) => makeSelectOptionElement(option, wireframe.value === option)) || []),
            ...children,
        ],
    }
}

function groupRadioButtons(children: serializedNodeWithId[], radioGroupName: string): serializedNodeWithId[] {
    return children.map((child) => {
        if (child.type === NodeType.Element && child.tagName === 'input' && child.attributes.type === 'radio') {
            return {
                ...child,
                attributes: {
                    ...child.attributes,
                    name: radioGroupName,
                },
            }
        }
        return child
    })
}

function makeRadioGroupElement(
    wireframe: wireframeRadioGroup,
    children: serializedNodeWithId[]
): serializedNodeWithId | null {
    const radioGroupName = 'radio_group_' + wireframe.id
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe),
        },
        id: wireframe.id,
        childNodes: groupRadioButtons(children, radioGroupName),
    }
}

function makeProgressElement(
    wireframe: wireframeProgress,
    children: serializedNodeWithId[]
): serializedNodeWithId | null {
    if (wireframe.style?.bar === 'circular') {
        // value needs to be expressed as a number between 0 and 100
        const max = wireframe.max || 1
        let value = wireframe.value || null
        if (_isPositiveInteger(value) && value <= max) {
            value = (value / max) * 100
        } else {
            value = null
        }

        return {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: makeMinimalStyles(wireframe),
            },
            id: wireframe.id,
            childNodes: [
                {
                    type: NodeType.Element,
                    tagName: 'div',
                    attributes: {
                        // with no provided value we render a spinner
                        style: _isPositiveInteger(value)
                            ? makeDeterminateProgressStyles(wireframe)
                            : makeIndeterminateProgressStyles(wireframe),
                    },
                    id: idSequence.next().value,
                    childNodes: [],
                },
                ...children,
            ],
        }
    } else {
        return {
            type: NodeType.Element,
            tagName: 'progress',
            attributes: inputAttributes(wireframe),
            id: wireframe.id,
            childNodes: children,
        }
    }
}

function makeToggleElement(
    wireframe: wireframeToggle,
    children: serializedNodeWithId[]
): (elementNode & { id: number }) | null {
    // first return simply a checkbox
    return {
        type: NodeType.Element,
        tagName: 'input',
        attributes: {
            ...inputAttributes(wireframe),
            type: 'checkbox',
        },
        id: wireframe.id,
        childNodes: children,
    }
}

function makeInputElement(
    wireframe: wireframeInputComponent,
    children: serializedNodeWithId[]
): serializedNodeWithId | null {
    if (!wireframe.inputType) {
        return null
    }

    if (wireframe.inputType === 'button') {
        return makeButtonElement(wireframe, children)
    }

    if (wireframe.inputType === 'select') {
        return makeSelectElement(wireframe, children)
    }

    if (wireframe.inputType === 'progress') {
        return makeProgressElement(wireframe, children)
    }

    const theInputElement: (elementNode & { id: number }) | null =
        wireframe.inputType === 'toggle'
            ? makeToggleElement(wireframe, children)
            : {
                  type: NodeType.Element,
                  tagName: 'input',
                  attributes: inputAttributes(wireframe),
                  id: wireframe.id,
                  childNodes: children,
              }
    if (!theInputElement) {
        return null
    }

    if ('label' in wireframe) {
        return {
            type: NodeType.Element,
            tagName: 'label',
            attributes: {
                style: makeStylesString(wireframe),
            },
            id: idSequence.next().value,
            childNodes: [
                theInputElement,
                {
                    type: NodeType.Text,
                    textContent: wireframe.label || '',
                    id: idSequence.next().value,
                },
            ],
        }
    } else {
        return {
            ...theInputElement,
            attributes: {
                ...theInputElement.attributes,
                // when labelled no styles are needed, when un-labelled as here - we add the styling in.
                style: makeStylesString(wireframe),
            },
        }
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
    // but since this is coming over the wire we can't really be sure,
    // and so we default to div
    const converterType: MobileNodeType = wireframe.type || 'div'
    const converterMapping: Record<
        MobileNodeType,
        (wireframe: T, children: serializedNodeWithId[]) => serializedNodeWithId | null
    > = {
        // KLUDGE: TS can't tell that the wireframe type of each function is safe based on the converter type
        text: makeTextElement as any,
        image: makeImageElement as any,
        rectangle: makeRectangleElement as any,
        div: makeDivElement as any,
        input: makeInputElement as any,
        radio_group: makeRadioGroupElement as any,
        web_view: makeWebViewElement as any,
        placeholder: makePlaceholderElement as any,
    }
    return converterMapping[converterType]
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

/**
 * We've not implemented mutations, until then this is almost an index function.
 *
 * But, we want to ensure that any mouse/touch events don't use id = 0.
 * They must always represent a valid ID from the dom, so we swap in the body id.
 *
 */
export const makeIncrementalEvent = (
    mobileEvent: MobileIncrementalSnapshotEvent & {
        timestamp: number
        delay?: number
    }
): incrementalSnapshotEvent & {
    timestamp: number
    delay?: number
} => {
    const converted = mobileEvent as unknown as incrementalSnapshotEvent & {
        timestamp: number
        delay?: number
    }
    if ('id' in converted.data && converted.data.id === 0) {
        converted.data.id = BODY_ID
    }
    return converted
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
                        attributes: { style: makeHTMLStyles() },
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
                                attributes: { style: makeBodyStyles() },
                                id: BODY_ID,
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
