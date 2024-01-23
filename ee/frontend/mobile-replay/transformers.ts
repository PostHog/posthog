import {
    addedNodeMutation,
    customEvent,
    EventType,
    fullSnapshotEvent,
    incrementalSnapshotEvent,
    IncrementalSource,
    metaEvent,
    mutationData,
    removedNodeMutation,
} from '@rrweb/types'
import {captureMessage} from '@sentry/react'
import {isObject} from 'lib/utils'

import {
    attributes,
    documentNode,
    elementNode,
    fullSnapshotEvent as MobileFullSnapshotEvent,
    keyboardEvent,
    metaEvent as MobileMetaEvent,
    MobileIncrementalSnapshotEvent,
    MobileNodeMutation,
    MobileNodeType,
    NodeType,
    serializedNodeWithId,
    textNode,
    wireframe,
    wireframeButton,
    wireframeCheckBox,
    wireframeDiv,
    wireframeImage,
    wireframeInputComponent,
    wireframePlaceholder,
    wireframeProgress,
    wireframeRadio,
    wireframeRadioGroup,
    wireframeRectangle,
    wireframeSelect,
    wireframeText,
    wireframeToggle,
} from './mobile.types'
import {makeStatusBar} from "./status-bar";
import {
    makeBodyStyles,
    makeColorStyles,
    makeDeterminateProgressStyles,
    makeHTMLStyles,
    makeIndeterminateProgressStyles,
    makeMinimalStyles,
    makePositionStyles,
    makeStylesString,
    StyleOverride,
} from './wireframeStyle'

const BACKGROUND = '#f3f4ef'
const FOREGROUND = '#35373e'

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

// there are some fixed ids that we need to use for fixed elements or artificial mutations
const DOCUMENT_ID = 1
const HTML_DOC_TYPE_ID = 2
const HTML_ELEMENT_ID = 3
const HEAD_ID = 4
const BODY_ID = 5
const KEYBOARD_ID = 6
export const STATUS_BAR_ID = 7

function isKeyboardEvent(x: unknown): x is keyboardEvent {
    return isObject(x) && 'data' in x && isObject(x.data) && 'tag' in x.data && x.data.tag === 'keyboard'
}

export const makeCustomEvent = (
    mobileCustomEvent: (customEvent | keyboardEvent) & {
        timestamp: number
        delay?: number
    }
): (customEvent | incrementalSnapshotEvent) & {
    timestamp: number
    delay?: number
} => {
    if (isKeyboardEvent(mobileCustomEvent)) {
        // keyboard events are handled as incremental snapshots to add or remove a keyboard from the DOM
        // TODO eventually we can pass something to makeIncrementalEvent here
        const adds: addedNodeMutation[] = []
        const removes = []
        if (mobileCustomEvent.data.payload.open) {
            const shouldAbsolutelyPosition =
                _isPositiveInteger(mobileCustomEvent.data.payload.x) ||
                _isPositiveInteger(mobileCustomEvent.data.payload.y)
            const styleOverride: StyleOverride | undefined = shouldAbsolutelyPosition ? undefined : { bottom: true }
            const keyboardPlaceHolder = makePlaceholderElement(
                {
                    id: KEYBOARD_ID,
                    type: 'placeholder',
                    label: 'keyboard',
                    height: mobileCustomEvent.data.payload.height,
                    width: _isPositiveInteger(mobileCustomEvent.data.payload.width)
                        ? mobileCustomEvent.data.payload.width
                        : '100vw',
                },
                [],
                styleOverride
            )
            if (keyboardPlaceHolder) {
                adds.push({
                    parentId: BODY_ID,
                    nextId: null,
                    node: keyboardPlaceHolder,
                })
                // mutations seem not to want a tree of nodes to add
                // so even though `keyboardPlaceholder` is a tree with content
                // we have to add the text content as well
                adds.push({
                    parentId: keyboardPlaceHolder.id,
                    nextId: null,
                    node: {
                        type: NodeType.Text,
                        id: idSequence.next().value,
                        textContent: 'keyboard',
                    },
                })
            } else {
                captureMessage('Failed to create keyboard placeholder', { extra: { mobileCustomEvent } })
            }
        } else {
            removes.push({
                parentId: BODY_ID,
                id: KEYBOARD_ID,
            })
        }
        const mutation: mutationData = { adds, attributes: [], removes, source: IncrementalSource.Mutation, texts: [] }
        return {
            type: EventType.IncrementalSnapshot,
            data: mutation,
            timestamp: mobileCustomEvent.timestamp,
        }
    } else {
        return mobileCustomEvent
    }
}

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

export function _isPositiveInteger(id: unknown): id is number {
    return typeof id === 'number' && id > 0 && id % 1 === 0
}

function makeDivElement(wireframe: wireframeDiv, children: serializedNodeWithId[]): serializedNodeWithId | null {
    const _id = _isPositiveInteger(wireframe.id) ? wireframe.id : idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe) + 'overflow:hidden;white-space:nowrap;',
            'data-rrweb-id': _id,
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
    const id = idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe) + 'overflow:hidden;white-space:nowrap;',
            'data-rrweb-id': wireframe.id,
        },
        id: wireframe.id,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: wireframe.text,
                // since the text node is wrapped, we assign it a synthetic id
                id: id,
            },
            ...children,
        ],
    }
}

function makeWebViewElement(wireframe: wireframe, children: serializedNodeWithId[]): serializedNodeWithId | null {
    const labelledWireframe: wireframePlaceholder = { ...wireframe } as wireframePlaceholder
    if ('url' in wireframe) {
        labelledWireframe.label = wireframe.url
    }

    return makePlaceholderElement(labelledWireframe, children)
}

function makePlaceholderElement(
    wireframe: wireframe,
    children: serializedNodeWithId[],
    styleOverride?: StyleOverride
): serializedNodeWithId | null {
    const txt = 'label' in wireframe && wireframe.label ? wireframe.label : wireframe.type || 'PLACEHOLDER'
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe, {
                verticalAlign: 'center',
                horizontalAlign: 'center',
                backgroundColor: wireframe.style?.backgroundColor || BACKGROUND,
                color: wireframe.style?.color || FOREGROUND,
                ...styleOverride,
            }),
            'data-rrweb-id': wireframe.id,
        },
        id: wireframe.id,
        childNodes: [
            {
                type: NodeType.Text,
                // since the text node is wrapped, we assign it a synthetic id
                id: idSequence.next().value,
                textContent: txt,
            },
            ...children,
        ],
    }
}

export function dataURIOrPNG(src: string):string {
    if (!src.startsWith('data:image/')) {
        return 'data:image/png;base64,' + src
    }
    return src;
}

function makeImageElement(wireframe: wireframeImage, children: serializedNodeWithId[]): serializedNodeWithId | null {
    if (!wireframe.base64) {
        return makePlaceholderElement(wireframe, children)
    }
    const src = dataURIOrPNG(wireframe.base64);
    return {
        type: NodeType.Element,
        tagName: 'img',
        attributes: {
            src: src,
            width: wireframe.width,
            height: wireframe.height,
            style: makeStylesString(wireframe),
            'data-rrweb-id': wireframe.id,
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
        'data-rrweb-id': wireframe.id,
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
    const optionId = idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'option',
        attributes: {
            ...(selected ? { selected: selected } : {}),
            'data-rrweb-id': optionId,
        },
        id: optionId,
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
                    'data-rrweb-id': child.id,
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
            'data-rrweb-id': wireframe.id,
        },
        id: wireframe.id,
        childNodes: groupRadioButtons(children, radioGroupName),
    }
}

function makeStar(title: string, path: string): serializedNodeWithId {
    const svgId = idSequence.next().value
    const titleId = idSequence.next().value
    const pathId = idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'svg',
        isSVG: true,
        attributes: {
            style: 'height: 100%;overflow-clip-margin: content-box;overflow:hidden',
            viewBox: '0 0 24 24',
            fill: 'currentColor',
            'data-rrweb-id': svgId,
        },
        id: svgId,
        childNodes: [
            {
                type: NodeType.Element,
                tagName: 'title',
                isSVG: true,
                attributes: {
                    'data-rrweb-id': titleId,
                },
                id: titleId,
                childNodes: [
                    {
                        type: NodeType.Text,
                        textContent: title,
                        id: idSequence.next().value,
                    },
                ],
            },
            {
                type: NodeType.Element,
                tagName: 'path',
                isSVG: true,
                attributes: {
                    d: path,
                    'data-rrweb-id': pathId,
                },
                id: pathId,
                childNodes: [],
            },
        ],
    }
}

function filledStar(): serializedNodeWithId {
    return makeStar(
        'filled star',
        'M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z'
    )
}

function halfStar(): serializedNodeWithId {
    return makeStar(
        'half-filled star',
        'M12,15.4V6.1L13.71,10.13L18.09,10.5L14.77,13.39L15.76,17.67M22,9.24L14.81,8.63L12,2L9.19,8.63L2,9.24L7.45,13.97L5.82,21L12,17.27L18.18,21L16.54,13.97L22,9.24Z'
    )
}

function emptyStar(): serializedNodeWithId {
    return makeStar(
        'empty star',
        'M12,15.39L8.24,17.66L9.23,13.38L5.91,10.5L10.29,10.13L12,6.09L13.71,10.13L18.09,10.5L14.77,13.38L15.76,17.66M22,9.24L14.81,8.63L12,2L9.19,8.63L2,9.24L7.45,13.97L5.82,21L12,17.27L18.18,21L16.54,13.97L22,9.24Z'
    )
}

function makeRatingBar(wireframe: wireframeProgress, children: serializedNodeWithId[]): serializedNodeWithId | null {
    // max is the number of stars... and value is the number of stars to fill

    // deliberate double equals, because we want to allow null and undefined
    if (wireframe.value == null || wireframe.max == null) {
        return makePlaceholderElement(wireframe, children)
    }

    const numberOfFilledStars = Math.floor(wireframe.value)
    const numberOfHalfStars = wireframe.value - numberOfFilledStars > 0 ? 1 : 0
    const numberOfEmptyStars = wireframe.max - numberOfFilledStars - numberOfHalfStars

    const filledStars = Array(numberOfFilledStars)
        .fill(undefined)
        .map(() => filledStar())
    const halfStars = Array(numberOfHalfStars)
        .fill(undefined)
        .map(() => halfStar())
    const emptyStars = Array(numberOfEmptyStars)
        .fill(undefined)
        .map(() => emptyStar())

    const ratingBarId = idSequence.next().value
    const ratingBar = {
        type: NodeType.Element,
        tagName: 'div',
        id: ratingBarId,
        attributes: {
            style:
                makeColorStyles(wireframe) +
                'position: relative; display: flex; flex-direction: row; padding: 2px 4px;',
            'data-rrweb-id': ratingBarId,
        },
        childNodes: [...filledStars, ...halfStars, ...emptyStars],
    } as serializedNodeWithId

    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe),
            'data-rrweb-id': wireframe.id,
        },
        id: wireframe.id,
        childNodes: [ratingBar, ...children],
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

        const styleOverride = {
            color: wireframe.style?.color || FOREGROUND,
            backgroundColor: wireframe.style?.backgroundColor || BACKGROUND,
        }

        // if not _isPositiveInteger(value) then we render a spinner,
        // so we need to add a style element with the spin keyframe
        const stylingChildren: serializedNodeWithId[] = _isPositiveInteger(value)
            ? []
            : [
                  {
                      type: NodeType.Element,
                      tagName: 'style',
                      attributes: {
                          type: 'text/css',
                      },
                      id: idSequence.next().value,
                      childNodes: [
                          {
                              type: NodeType.Text,
                              textContent: `@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }`,
                              id: idSequence.next().value,
                          },
                      ],
                  },
              ]

        const wrappingDivId = idSequence.next().value
        return {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: makeMinimalStyles(wireframe),
                'data-rrweb-id': wireframe.id,
            },
            id: wireframe.id,
            childNodes: [
                {
                    type: NodeType.Element,
                    tagName: 'div',
                    attributes: {
                        // with no provided value we render a spinner
                        style: _isPositiveInteger(value)
                            ? makeDeterminateProgressStyles(wireframe, styleOverride)
                            : makeIndeterminateProgressStyles(wireframe, styleOverride),
                        'data-rrweb-id': wrappingDivId,
                    },
                    id: wrappingDivId,
                    childNodes: stylingChildren,
                },
                ...children,
            ],
        }
    } else if (wireframe.style?.bar === 'rating') {
        return makeRatingBar(wireframe, children)
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

function makeToggleParts(wireframe: wireframeToggle): serializedNodeWithId[] {
    const togglePosition = wireframe.checked ? 'right' : 'left'
    const defaultColor = wireframe.checked ? '#1d4aff' : BACKGROUND
    const sliderPartId = idSequence.next().value
    const handlePartId = idSequence.next().value
    return [
        {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                'data-toggle-part': 'slider',
                style: `position:absolute;top:33%;left:5%;display:inline-block;width:75%;height:33%;background-color:${
                    wireframe.style?.color || defaultColor
                };opacity: 0.2;border-radius:7.5%;`,
                'data-rrweb-id': sliderPartId,
            },
            id: sliderPartId,
            childNodes: [],
        },
        {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                'data-toggle-part': 'handle',
                style: `position:absolute;top:1.5%;${togglePosition}:5%;display:flex;align-items:center;justify-content:center;width:40%;height:75%;cursor:inherit;background-color:${
                    wireframe.style?.color || defaultColor
                };border:2px solid ${
                    wireframe.style?.borderColor || wireframe.style?.color || defaultColor
                };border-radius:50%;`,
                'data-rrweb-id': handlePartId,
            },
            id: handlePartId,
            childNodes: [],
        },
    ]
}

function makeToggleElement(wireframe: wireframeToggle): (elementNode & { id: number }) | null {
    const isLabelled = 'label' in wireframe
    const wrappingDivId = idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            // if labelled take up available space, otherwise use provided positioning
            style: isLabelled ? `height:100%;flex:1` : makePositionStyles(wireframe),
            'data-rrweb-id': wireframe.id,
        },
        id: wireframe.id,
        childNodes: [
            {
                type: NodeType.Element,
                tagName: 'div',
                attributes: {
                    // relative position, fills parent
                    style: 'position:relative;width:100%;height:100%;',
                    'data-rrweb-id': wrappingDivId,
                },
                id: wrappingDivId,
                childNodes: makeToggleParts(wireframe),
            },
        ],
    }
}

function makeLabelledInput(
    wireframe: wireframeCheckBox | wireframeRadio | wireframeToggle,
    theInputElement: serializedNodeWithId
): serializedNodeWithId {
    const theLabel: serializedNodeWithId = {
        type: NodeType.Text,
        textContent: wireframe.label || '',
        id: idSequence.next().value,
    }

    const orderedChildren = wireframe.inputType === 'toggle' ? [theLabel, theInputElement] : [theInputElement, theLabel]

    const labelId = idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'label',
        attributes: {
            style: makeStylesString(wireframe),
            'data-rrweb-id': labelId,
        },
        id: labelId,
        childNodes: orderedChildren,
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

    const theInputElement: serializedNodeWithId | null =
        wireframe.inputType === 'toggle'
            ? makeToggleElement(wireframe)
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
        return makeLabelledInput(wireframe, theInputElement)
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
        tagName: 'div',
        attributes: {
            style: makeStylesString(wireframe),
            'data-rrweb-id': wireframe.id,
        },
        id: wireframe.id,
        childNodes: children,
    }
}

function chooseConverter<T extends wireframe>(
    wireframe: T
): (wireframe: T, children: serializedNodeWithId[], timestamp?: number, idSequence?: Generator<number>) => serializedNodeWithId | null {
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
        status_bar: makeStatusBar as any,
        // we could add in a converter for this, but it's fine without any chrome for now
        navigation_bar: makeDivElement as any,
    }
    return converterMapping[converterType]
}

function convertWireframe(wireframe: wireframe, timestamp?: number, idSequence?: Generator<number>): serializedNodeWithId | null {
    const children = convertWireframesFor(wireframe.childWireframes, timestamp)
    const converter = chooseConverter(wireframe)
    return converter?.(wireframe, children, timestamp, idSequence) || null
}

function convertWireframesFor(wireframes: wireframe[] | undefined, timestamp?: number): serializedNodeWithId[] {
    if (!wireframes) {
        return []
    }

    return wireframes.reduce((acc, wireframe) => {
        const convertedEl = convertWireframe(wireframe, timestamp, idSequence)
        if (convertedEl !== null) {
            acc.push(convertedEl)
        }
        return acc
    }, [] as serializedNodeWithId[])
}

function isMobileIncrementalSnapshotEvent(x: unknown): x is MobileIncrementalSnapshotEvent {
    const isIncrementalSnapshot = isObject(x) && 'type' in x && x.type === EventType.IncrementalSnapshot
    if (!isIncrementalSnapshot) {
        return false
    }
    const hasData = isObject(x) && 'data' in x
    const data = hasData ? x.data : null

    const hasMutationSource = isObject(data) && 'source' in data && data.source === IncrementalSource.Mutation

    const adds = isObject(data) && 'adds' in data && Array.isArray(data.adds) ? data.adds : null
    const updates = isObject(data) && 'updates' in data && Array.isArray(data.updates) ? data.updates : null

    const hasUpdatedWireframe = !!updates && updates.length > 0 && isObject(updates[0]) && 'wireframe' in updates[0]
    const hasAddedWireframe = !!adds && adds.length > 0 && isObject(adds[0]) && 'wireframe' in adds[0]

    return hasMutationSource && (hasAddedWireframe || hasUpdatedWireframe)
}

function makeIncrementalAdd(add: MobileNodeMutation): addedNodeMutation[] | null {
    const converted = convertWireframe(add.wireframe, undefined, idSequence)
    if (!converted) {
        return null
    }

    const addition: addedNodeMutation = {
        parentId: add.parentId,
        nextId: null,
        node: converted,
    }
    const adds: addedNodeMutation[] = []
    if (addition) {
        const flattened = flattenMutationAdds(addition)
        flattened.forEach((x) => adds.push(x))
        return adds
    } else {
        return null
    }
}

/**
 * When processing an update we remove the entire item, and then add it back in.
 */
function makeIncrementalRemoveForUpdate(update: MobileNodeMutation): removedNodeMutation {
    return {
        parentId: update.parentId,
        id: update.wireframe.id,
    }
}

function isNode(x: unknown): x is serializedNodeWithId {
    // KLUDGE: really we should check that x.type is valid, but we're safe enough already
    return isObject(x) && 'type' in x && 'id' in x
}

function isNodeWithChildren(x: unknown): x is elementNode | documentNode {
    return isNode(x) && 'childNodes' in x && Array.isArray(x.childNodes)
}

/**
 * when creating incremental adds we have to flatten the node tree structure
 * there's no point, then keeping those child nodes in place
 */
function cloneWithoutChildren(converted: addedNodeMutation): addedNodeMutation {
    const cloned = { ...converted }
    const clonedNode: serializedNodeWithId = { ...converted.node }
    if (isNodeWithChildren(clonedNode)) {
        clonedNode.childNodes = []
    }
    cloned.node = clonedNode
    return cloned
}

function flattenMutationAdds(converted: addedNodeMutation): addedNodeMutation[] {
    const flattened: addedNodeMutation[] = []

    flattened.push(cloneWithoutChildren(converted))

    const node: unknown = converted.node
    const newParentId = converted.node.id
    if (isNodeWithChildren(node)) {
        node.childNodes.forEach((child) => {
            flattened.push(
                cloneWithoutChildren({
                    parentId: newParentId,
                    nextId: null,
                    node: child,
                })
            )
            if (isNodeWithChildren(child)) {
                flattened.push(...flattenMutationAdds({ parentId: newParentId, nextId: null, node: child }))
            }
        })
    }
    return flattened
}

/**
 * We want to ensure that any events don't use id = 0.
 * They must always represent a valid ID from the dom, so we swap in the body id when the id = 0.
 *
 * For "removes", we don't need to do anything, the id of the element to be removed remains valid. We won't try and remove other elements that we added during transformation in order to show that element.
 *
 * "adds" are converted from wireframes to nodes and converted to `incrementalSnapshotEvent.adds`
 *
 * "updates" are converted to a remove and an add.
 *
 */
export const makeIncrementalEvent = (
    mobileEvent: (MobileIncrementalSnapshotEvent | incrementalSnapshotEvent) & {
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

    if (isMobileIncrementalSnapshotEvent(mobileEvent)) {
        const adds: addedNodeMutation[] = []
        const removes: removedNodeMutation[] = mobileEvent.data.removes || []
        if ('adds' in mobileEvent.data && Array.isArray(mobileEvent.data.adds)) {
            mobileEvent.data.adds.forEach((add) => {
                makeIncrementalAdd(add)?.forEach((x) => adds.push(x))
            })
        }
        if ('updates' in mobileEvent.data && Array.isArray(mobileEvent.data.updates)) {
            mobileEvent.data.updates.forEach((update) => {
                const removal = makeIncrementalRemoveForUpdate(update)
                if (removal) {
                    removes.push(removal)
                }
                makeIncrementalAdd(update)?.forEach((x) => adds.push(x))
            })
        }

        converted.data = {
            source: IncrementalSource.Mutation,
            attributes: [],
            texts: [],
            adds,
            // TODO: this assumes that removes are processed before adds 🤞
            removes,
        }
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
                        id: HTML_DOC_TYPE_ID,
                    },
                    {
                        type: NodeType.Element,
                        tagName: 'html',
                        attributes: { style: makeHTMLStyles(), 'data-rrweb-id': HTML_ELEMENT_ID },
                        id: HTML_ELEMENT_ID,
                        childNodes: [
                            {
                                type: NodeType.Element,
                                tagName: 'head',
                                attributes: { 'data-rrweb-id': HEAD_ID },
                                id: HEAD_ID,
                                childNodes: [],
                            },
                            {
                                type: NodeType.Element,
                                tagName: 'body',
                                attributes: { style: makeBodyStyles(), 'data-rrweb-id': BODY_ID },
                                id: BODY_ID,
                                childNodes: convertWireframesFor(mobileEvent.data.wireframes, mobileEvent.timestamp) || [],
                            },
                        ],
                    },
                ],
                id: DOCUMENT_ID,
            },
            initialOffset: {
                top: 0,
                left: 0,
            },
        },
    }
}
