import posthog from 'posthog-js'

import {
    EventType,
    IncrementalSource,
    addedNodeMutation,
    customEvent,
    fullSnapshotEvent,
    incrementalSnapshotEvent,
    metaEvent,
    mutationData,
    removedNodeMutation,
} from '@posthog/rrweb-types'

import { isObject } from 'lib/utils'
import { PLACEHOLDER_SVG_DATA_IMAGE_URL } from 'scenes/session-recordings/player/rrweb'

import {
    fullSnapshotEvent as MobileFullSnapshotEvent,
    MobileIncrementalSnapshotEvent,
    metaEvent as MobileMetaEvent,
    MobileNodeMutation,
    MobileNodeType,
    NodeType,
    attributes,
    documentNode,
    elementNode,
    keyboardEvent,
    serializedNodeWithId,
    textNode,
    wireframe,
    wireframeButton,
    wireframeCheckBox,
    wireframeDiv,
    wireframeImage,
    wireframeInputComponent,
    wireframeNavigationBar,
    wireframePlaceholder,
    wireframeProgress,
    wireframeRadio,
    wireframeRadioGroup,
    wireframeRectangle,
    wireframeScreenshot,
    wireframeSelect,
    wireframeStatusBar,
    wireframeText,
    wireframeToggle,
} from '../mobile.types'
import { makeNavigationBar, makeOpenKeyboardPlaceholder, makeStatusBar } from './screen-chrome'
import { ConversionContext, ConversionResult } from './types'
import {
    asStyleString,
    makeBodyStyles,
    makeColorStyles,
    makeDeterminateProgressStyles,
    makeHTMLStyles,
    makeIndeterminateProgressStyles,
    makeMinimalStyles,
    makePositionStyles,
    makeStylesString,
} from './wireframeStyle'

export const BACKGROUND = '#f3f4ef'
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

let globalIdSequence = ids()

// there are some fixed ids that we need to use for fixed elements or artificial mutations
const DOCUMENT_ID = 1
const HTML_DOC_TYPE_ID = 2
const HTML_ELEMENT_ID = 3
const HEAD_ID = 4
const BODY_ID = 5
// the nav bar should always be the last item in the body so that it is at the top of the stack
const NAVIGATION_BAR_PARENT_ID = 7
export const NAVIGATION_BAR_ID = 8
// the keyboard so that it is still before the nav bar
const KEYBOARD_PARENT_ID = 9
export const KEYBOARD_ID = 10
export const STATUS_BAR_PARENT_ID = 11
export const STATUS_BAR_ID = 12

function isKeyboardEvent(x: unknown): x is keyboardEvent {
    return isObject(x) && 'data' in x && isObject(x.data) && 'tag' in x.data && x.data.tag === 'keyboard'
}

export function _isPositiveInteger(id: unknown): id is number {
    return typeof id === 'number' && id > 0 && id % 1 === 0
}

function _isNullish(x: unknown): x is null | undefined {
    return x === null || x === undefined
}

function isRemovedNodeMutation(x: addedNodeMutation | removedNodeMutation): x is removedNodeMutation {
    return isObject(x) && 'id' in x
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
            const keyboardPlaceHolder = makeOpenKeyboardPlaceholder(mobileCustomEvent, {
                timestamp: mobileCustomEvent.timestamp,
                idSequence: globalIdSequence,
            })
            if (keyboardPlaceHolder) {
                adds.push({
                    parentId: KEYBOARD_PARENT_ID,
                    nextId: null,
                    node: keyboardPlaceHolder.result,
                })
                // mutations seem not to want a tree of nodes to add
                // so even though `keyboardPlaceholder` is a tree with content
                // we have to add the text content as well
                adds.push({
                    parentId: keyboardPlaceHolder.result.id,
                    nextId: null,
                    node: {
                        type: NodeType.Text,
                        id: globalIdSequence.next().value,
                        textContent: 'keyboard',
                    },
                })
            } else {
                posthog.captureException(new Error('Failed to create keyboard placeholder'), { mobileCustomEvent })
            }
        } else {
            removes.push({
                parentId: KEYBOARD_PARENT_ID,
                id: KEYBOARD_ID,
            })
        }
        const mutation: mutationData = { adds, attributes: [], removes, source: IncrementalSource.Mutation, texts: [] }
        return {
            type: EventType.IncrementalSnapshot,
            data: mutation,
            timestamp: mobileCustomEvent.timestamp,
        }
    }
    return mobileCustomEvent
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

export function makeDivElement(
    wireframe: wireframeDiv,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    const _id = _isPositiveInteger(wireframe.id) ? wireframe.id : context.idSequence.next().value
    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: asStyleString([makeStylesString(wireframe), 'overflow:hidden', 'white-space:nowrap']),
                'data-rrweb-id': _id,
            },
            id: _id,
            childNodes: children,
        },
        context,
    }
}

function makeTextElement(
    wireframe: wireframeText,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    if (wireframe.type !== 'text') {
        console.error('Passed incorrect wireframe type to makeTextElement')
        return null
    }

    // because we might have to style the text, we always wrap it in a div
    // and apply styles to that
    const id = context.idSequence.next().value

    const childNodes = [...children]
    if (!_isNullish(wireframe.text)) {
        childNodes.unshift({
            type: NodeType.Text,
            textContent: wireframe.text,
            // since the text node is wrapped, we assign it a synthetic id
            id,
        })
    }

    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: asStyleString([makeStylesString(wireframe), 'overflow:hidden', 'white-space:normal']),
                'data-rrweb-id': wireframe.id,
            },
            id: wireframe.id,
            childNodes,
        },
        context,
    }
}

function makeWebViewElement(
    wireframe: wireframe,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    const labelledWireframe: wireframePlaceholder = { ...wireframe } as wireframePlaceholder
    if ('url' in wireframe) {
        labelledWireframe.label = wireframe.url
    }

    return makePlaceholderElement(labelledWireframe, children, context)
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
                    // since the text node is wrapped, we assign it a synthetic id
                    id: context.idSequence.next().value,
                    textContent: txt,
                },
                ...children,
            ],
        },
        context,
    }
}

export function dataURIOrPNG(src: string): string {
    // replace all new lines in src
    src = src.replace(/\r?\n|\r/g, '')
    if (!src.startsWith('data:image/')) {
        return 'data:image/png;base64,' + src
    }
    return src
}

function makeImageElement(
    wireframe: wireframeImage | wireframeScreenshot,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    if (!wireframe.base64) {
        return makePlaceholderElement(wireframe, children, context)
    }

    const src = dataURIOrPNG(wireframe.base64)
    return {
        result: {
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
        },
        context,
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

function makeButtonElement(
    wireframe: wireframeButton,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    const buttonText: textNode | null = wireframe.value
        ? {
              type: NodeType.Text,
              textContent: wireframe.value,
          }
        : null

    return {
        result: {
            type: NodeType.Element,
            tagName: 'button',
            attributes: inputAttributes(wireframe),
            id: wireframe.id,
            childNodes: buttonText ? [{ ...buttonText, id: context.idSequence.next().value }, ...children] : children,
        },
        context,
    }
}

function makeSelectOptionElement(
    option: string,
    selected: boolean,
    context: ConversionContext
): ConversionResult<serializedNodeWithId> {
    const optionId = context.idSequence.next().value
    return {
        result: {
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
                    id: context.idSequence.next().value,
                },
            ],
        },
        context,
    }
}

function makeSelectElement(
    wireframe: wireframeSelect,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    const selectOptions: serializedNodeWithId[] = []
    if (wireframe.options) {
        let optionContext = context
        for (let i = 0; i < wireframe.options.length; i++) {
            const option = wireframe.options[i]
            const conversion = makeSelectOptionElement(option, wireframe.value === option, optionContext)
            selectOptions.push(conversion.result)
            optionContext = conversion.context
        }
    }
    return {
        result: {
            type: NodeType.Element,
            tagName: 'select',
            attributes: inputAttributes(wireframe),
            id: wireframe.id,
            childNodes: [...selectOptions, ...children],
        },
        context,
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
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    const radioGroupName = 'radio_group_' + wireframe.id
    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: makeStylesString(wireframe),
                'data-rrweb-id': wireframe.id,
            },
            id: wireframe.id,
            childNodes: groupRadioButtons(children, radioGroupName),
        },
        context,
    }
}

function makeStar(title: string, path: string, context: ConversionContext): serializedNodeWithId {
    const svgId = context.idSequence.next().value
    const titleId = context.idSequence.next().value
    const pathId = context.idSequence.next().value
    return {
        type: NodeType.Element,
        tagName: 'svg',
        isSVG: true,
        attributes: {
            style: asStyleString(['height: 100%', 'overflow-clip-margin: content-box', 'overflow:hidden']),
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
                        id: context.idSequence.next().value,
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

function filledStar(context: ConversionContext): serializedNodeWithId {
    return makeStar(
        'filled star',
        'M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z',
        context
    )
}

function halfStar(context: ConversionContext): serializedNodeWithId {
    return makeStar(
        'half-filled star',
        'M12,15.4V6.1L13.71,10.13L18.09,10.5L14.77,13.39L15.76,17.67M22,9.24L14.81,8.63L12,2L9.19,8.63L2,9.24L7.45,13.97L5.82,21L12,17.27L18.18,21L16.54,13.97L22,9.24Z',
        context
    )
}

function emptyStar(context: ConversionContext): serializedNodeWithId {
    return makeStar(
        'empty star',
        'M12,15.39L8.24,17.66L9.23,13.38L5.91,10.5L10.29,10.13L12,6.09L13.71,10.13L18.09,10.5L14.77,13.38L15.76,17.66M22,9.24L14.81,8.63L12,2L9.19,8.63L2,9.24L7.45,13.97L5.82,21L12,17.27L18.18,21L16.54,13.97L22,9.24Z',
        context
    )
}

function makeRatingBar(
    wireframe: wireframeProgress,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    // max is the number of stars... and value is the number of stars to fill

    // deliberate double equals, because we want to allow null and undefined
    if (wireframe.value == null || wireframe.max == null) {
        return makePlaceholderElement(wireframe, children, context)
    }

    const numberOfFilledStars = Math.floor(wireframe.value)
    const numberOfHalfStars = wireframe.value - numberOfFilledStars > 0 ? 1 : 0
    const numberOfEmptyStars = wireframe.max - numberOfFilledStars - numberOfHalfStars

    const filledStars = Array(numberOfFilledStars)
        .fill(undefined)
        .map(() => filledStar(context))
    const halfStars = Array(numberOfHalfStars)
        .fill(undefined)
        .map(() => halfStar(context))
    const emptyStars = Array(numberOfEmptyStars)
        .fill(undefined)
        .map(() => emptyStar(context))

    const ratingBarId = context.idSequence.next().value
    const ratingBar = {
        type: NodeType.Element,
        tagName: 'div',
        id: ratingBarId,
        attributes: {
            style: asStyleString([
                makeColorStyles(wireframe),
                'position: relative',
                'display: flex',
                'flex-direction: row',
                'padding: 2px 4px',
            ]),
            'data-rrweb-id': ratingBarId,
        },
        childNodes: [...filledStars, ...halfStars, ...emptyStars],
    } as serializedNodeWithId

    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: makeStylesString(wireframe),
                'data-rrweb-id': wireframe.id,
            },
            id: wireframe.id,
            childNodes: [ratingBar, ...children],
        },
        context,
    }
}

function makeProgressElement(
    wireframe: wireframeProgress,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
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
                      id: context.idSequence.next().value,
                      childNodes: [
                          {
                              type: NodeType.Text,
                              textContent: `@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }`,
                              id: context.idSequence.next().value,
                          },
                      ],
                  },
              ]

        const wrappingDivId = context.idSequence.next().value
        return {
            result: {
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
            },
            context,
        }
    } else if (wireframe.style?.bar === 'rating') {
        return makeRatingBar(wireframe, children, context)
    }
    return {
        result: {
            type: NodeType.Element,
            tagName: 'progress',
            attributes: inputAttributes(wireframe),
            id: wireframe.id,
            childNodes: children,
        },
        context,
    }
}

function makeToggleParts(wireframe: wireframeToggle, context: ConversionContext): serializedNodeWithId[] {
    const togglePosition = wireframe.checked ? 'right' : 'left'
    const defaultColor = wireframe.checked ? '#1d4aff' : BACKGROUND
    const sliderPartId = context.idSequence.next().value
    const handlePartId = context.idSequence.next().value
    return [
        {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                'data-toggle-part': 'slider',
                style: asStyleString([
                    'position:absolute',
                    'top:33%',
                    'left:5%',
                    'display:inline-block',
                    'width:75%',
                    'height:33%',
                    'opacity: 0.2',
                    'border-radius:7.5%',
                    `background-color:${wireframe.style?.color || defaultColor}`,
                ]),
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
                style: asStyleString([
                    'position:absolute',
                    'top:1.5%',
                    `${togglePosition}:5%`,
                    'display:flex',
                    'align-items:center',
                    'justify-content:center',
                    'width:40%',
                    'height:75%',
                    'cursor:inherit',
                    'border-radius:50%',
                    `background-color:${wireframe.style?.color || defaultColor}`,
                    `border:2px solid ${wireframe.style?.borderColor || wireframe.style?.color || defaultColor}`,
                ]),
                'data-rrweb-id': handlePartId,
            },
            id: handlePartId,
            childNodes: [],
        },
    ]
}

function makeToggleElement(
    wireframe: wireframeToggle,
    context: ConversionContext
): ConversionResult<
    elementNode & {
        id: number
    }
> | null {
    const isLabelled = 'label' in wireframe
    const wrappingDivId = context.idSequence.next().value
    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                // if labelled take up available space, otherwise use provided positioning
                style: isLabelled ? asStyleString(['height:100%', 'flex:1']) : makePositionStyles(wireframe),
                'data-rrweb-id': wireframe.id,
            },
            id: wireframe.id,
            childNodes: [
                {
                    type: NodeType.Element,
                    tagName: 'div',
                    attributes: {
                        // relative position, fills parent
                        style: asStyleString(['position:relative', 'width:100%', 'height:100%']),
                        'data-rrweb-id': wrappingDivId,
                    },
                    id: wrappingDivId,
                    childNodes: makeToggleParts(wireframe, context),
                },
            ],
        },
        context,
    }
}

function makeLabelledInput(
    wireframe: wireframeCheckBox | wireframeRadio | wireframeToggle,
    theInputElement: serializedNodeWithId,
    context: ConversionContext
): ConversionResult<serializedNodeWithId> {
    const theLabel: serializedNodeWithId = {
        type: NodeType.Text,
        textContent: wireframe.label || '',
        id: context.idSequence.next().value,
    }

    const orderedChildren = wireframe.inputType === 'toggle' ? [theLabel, theInputElement] : [theInputElement, theLabel]

    const labelId = context.idSequence.next().value
    return {
        result: {
            type: NodeType.Element,
            tagName: 'label',
            attributes: {
                style: makeStylesString(wireframe),
                'data-rrweb-id': labelId,
            },
            id: labelId,
            childNodes: orderedChildren,
        },
        context,
    }
}

function makeInputElement(
    wireframe: wireframeInputComponent,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    if (!wireframe.inputType) {
        return null
    }

    if (wireframe.inputType === 'button') {
        return makeButtonElement(wireframe, children, context)
    }

    if (wireframe.inputType === 'select') {
        return makeSelectElement(wireframe, children, context)
    }

    if (wireframe.inputType === 'progress') {
        return makeProgressElement(wireframe, children, context)
    }

    const theInputElement: ConversionResult<serializedNodeWithId> | null =
        wireframe.inputType === 'toggle'
            ? makeToggleElement(wireframe, context)
            : {
                  result: {
                      type: NodeType.Element,
                      tagName: 'input',
                      attributes: inputAttributes(wireframe),
                      id: wireframe.id,
                      childNodes: children,
                  },
                  context,
              }

    if (!theInputElement) {
        return null
    }

    if ('label' in wireframe) {
        return makeLabelledInput(wireframe, theInputElement.result, theInputElement.context)
    }
    // when labelled no styles are needed, when un-labelled as here - we add the styling in.
    ;(theInputElement.result as elementNode).attributes.style = makeStylesString(wireframe)
    return theInputElement
}

function makeRectangleElement(
    wireframe: wireframeRectangle,
    children: serializedNodeWithId[],
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    return {
        result: {
            type: NodeType.Element,
            tagName: 'div',
            attributes: {
                style: makeStylesString(wireframe),
                'data-rrweb-id': wireframe.id,
            },
            id: wireframe.id,
            childNodes: children,
        },
        context,
    }
}

function chooseConverter<T extends wireframe>(
    wireframe: T
): (
    wireframe: T,
    children: serializedNodeWithId[],
    context: ConversionContext
) => ConversionResult<serializedNodeWithId> | null {
    // in theory type is always present
    // but since this is coming over the wire we can't really be sure,
    // and so we default to div
    const converterType: MobileNodeType = wireframe.type || 'div'
    const converterMapping: Record<
        MobileNodeType,
        (wireframe: T, children: serializedNodeWithId[]) => ConversionResult<serializedNodeWithId> | null
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
        navigation_bar: makeNavigationBar as any,
        screenshot: makeImageElement as any,
    }
    return converterMapping[converterType]
}

function convertWireframe(
    wireframe: wireframe,
    context: ConversionContext
): ConversionResult<serializedNodeWithId> | null {
    const children = convertWireframesFor(wireframe.childWireframes, context)
    const converted = chooseConverter(wireframe)?.(wireframe, children.result, children.context)
    return converted || null
}

function convertWireframesFor(
    wireframes: wireframe[] | undefined,
    context: ConversionContext
): ConversionResult<serializedNodeWithId[]> {
    if (!wireframes) {
        return { result: [], context }
    }

    const result: serializedNodeWithId[] = []
    for (const wireframe of wireframes) {
        const converted = convertWireframe(wireframe, context)
        if (converted) {
            result.push(converted.result)
            context = converted.context
        }
    }
    return { result, context }
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

function chooseParentId(nodeType: MobileNodeType, providedParentId: number): number {
    return nodeType === 'screenshot' ? BODY_ID : providedParentId
}

function makeIncrementalAdd(add: MobileNodeMutation, context: ConversionContext): addedNodeMutation[] | null {
    const converted = convertWireframe(add.wireframe, context)

    if (!converted) {
        return null
    }

    const addition: addedNodeMutation = {
        parentId: chooseParentId(add.wireframe.type, add.parentId),
        nextId: null,
        node: converted.result,
    }
    const adds: addedNodeMutation[] = []
    if (addition) {
        const flattened = flattenMutationAdds(addition)
        flattened.forEach((x) => adds.push(x))
        return adds
    }
    return null
}

/**
 * When processing an update we remove the entire item, and then add it back in.
 */
function makeIncrementalRemoveForUpdate(update: MobileNodeMutation): removedNodeMutation {
    return {
        parentId: chooseParentId(update.wireframe.type, update.parentId),
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
 * each update wireframe carries the entire tree because we don't want to diff on the client
 * that means that we might create multiple mutations for the same node
 * we only want to add it once, so we dedupe the mutations
 * the app guarantees that for a given ID that is present more than once in a single snapshot
 * every instance of that ID is identical
 * it might change in the next snapshot but for a single incremental snapshot there is one
 * and only one version of any given ID
 */
function dedupeMutations<T extends addedNodeMutation | removedNodeMutation>(mutations: T[]): T[] {
    // KLUDGE: it's slightly yucky to stringify everything but since synthetic nodes
    // introduce a new id, we can't just compare the id
    const seen = new Set<string>()

    // in case later mutations are the ones we want to keep, we reverse the array
    // this does help with the deduping, so, it's likely that the view for a single ID
    // is not consistent over a snapshot, but it's cheap to reverse so :YOLO:
    return mutations
        .reverse()
        .filter((mutation: addedNodeMutation | removedNodeMutation) => {
            let toCompare: string
            if (isRemovedNodeMutation(mutation)) {
                toCompare = JSON.stringify(mutation)
            } else {
                // if this is a synthetic addition, then we need to ignore the id,
                // since duplicates won't have duplicate ids
                toCompare = JSON.stringify({
                    ...mutation.node,
                    id: 0,
                })
            }

            if (seen.has(toCompare)) {
                return false
            }
            seen.add(toCompare)
            return true
        })
        .reverse()
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
            const addsContext = {
                timestamp: mobileEvent.timestamp,
                idSequence: globalIdSequence,
            }

            mobileEvent.data.adds.forEach((add) => {
                makeIncrementalAdd(add, addsContext)?.forEach((x) => adds.push(x))
            })
        }
        if ('updates' in mobileEvent.data && Array.isArray(mobileEvent.data.updates)) {
            const updatesContext = {
                timestamp: mobileEvent.timestamp,
                idSequence: globalIdSequence,
            }
            const updateAdditions: addedNodeMutation[] = []
            mobileEvent.data.updates.forEach((update) => {
                const removal = makeIncrementalRemoveForUpdate(update)
                if (removal) {
                    removes.push(removal)
                }
                makeIncrementalAdd(update, updatesContext)?.forEach((x) => updateAdditions.push(x))
            })
            dedupeMutations(updateAdditions).forEach((x) => adds.push(x))
        }

        converted.data = {
            source: IncrementalSource.Mutation,
            attributes: [],
            texts: [],
            adds: dedupeMutations(adds),
            // TODO: this assumes that removes are processed before adds 🤞
            removes: dedupeMutations(removes),
        }
    }

    return converted
}

function makeKeyboardParent(): serializedNodeWithId {
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            'data-render-reason': 'a fixed placeholder to contain the keyboard in the correct stacking position',
            'data-rrweb-id': KEYBOARD_PARENT_ID,
        },
        id: KEYBOARD_PARENT_ID,
        childNodes: [],
    }
}

function makeStatusBarNode(
    statusBar: wireframeStatusBar | undefined,
    context: ConversionContext
): serializedNodeWithId {
    const childNodes = statusBar ? convertWireframesFor([statusBar], context).result : []
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            'data-rrweb-id': STATUS_BAR_PARENT_ID,
        },
        id: STATUS_BAR_PARENT_ID,
        childNodes,
    }
}

function makeNavBarNode(
    navigationBar: wireframeNavigationBar | undefined,
    context: ConversionContext
): serializedNodeWithId {
    const childNodes = navigationBar ? convertWireframesFor([navigationBar], context).result : []
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            'data-rrweb-id': NAVIGATION_BAR_PARENT_ID,
        },
        id: NAVIGATION_BAR_PARENT_ID,
        childNodes,
    }
}

function stripBarsFromWireframe(wireframe: wireframe): {
    wireframe: wireframe | undefined
    statusBar: wireframeStatusBar | undefined
    navBar: wireframeNavigationBar | undefined
} {
    if (wireframe.type === 'status_bar') {
        return { wireframe: undefined, statusBar: wireframe, navBar: undefined }
    } else if (wireframe.type === 'navigation_bar') {
        return { wireframe: undefined, statusBar: undefined, navBar: wireframe }
    }
    let statusBar: wireframeStatusBar | undefined
    let navBar: wireframeNavigationBar | undefined
    const wireframeToReturn: wireframe | undefined = { ...wireframe }
    wireframeToReturn.childWireframes = []
    for (const child of wireframe.childWireframes || []) {
        const {
            wireframe: childWireframe,
            statusBar: childStatusBar,
            navBar: childNavBar,
        } = stripBarsFromWireframe(child)
        statusBar = statusBar || childStatusBar
        navBar = navBar || childNavBar
        if (childWireframe) {
            wireframeToReturn.childWireframes.push(childWireframe)
        }
    }
    return { wireframe: wireframeToReturn, statusBar, navBar }
}

/**
 * We want to be able to place the status bar and navigation bar in the correct stacking order.
 * So, we lift them out of the tree, and return them separately.
 */
export function stripBarsFromWireframes(wireframes: wireframe[]): {
    statusBar: wireframeStatusBar | undefined
    navigationBar: wireframeNavigationBar | undefined
    appNodes: wireframe[]
} {
    let statusBar: wireframeStatusBar | undefined
    let navigationBar: wireframeNavigationBar | undefined
    const copiedNodes: wireframe[] = []

    wireframes.forEach((w) => {
        const matches = stripBarsFromWireframe(w)
        if (matches.statusBar) {
            statusBar = matches.statusBar
        }
        if (matches.navBar) {
            navigationBar = matches.navBar
        }
        if (matches.wireframe) {
            copiedNodes.push(matches.wireframe)
        }
    })
    return { statusBar, navigationBar, appNodes: copiedNodes }
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
    // we can restart the id sequence on each full snapshot
    globalIdSequence = ids()

    if (!(isObject(mobileEvent.data) && 'wireframes' in mobileEvent.data)) {
        return mobileEvent as unknown as fullSnapshotEvent & {
            timestamp: number
            delay?: number
        }
    }

    const conversionContext = {
        timestamp: mobileEvent.timestamp,
        idSequence: globalIdSequence,
    }

    const { statusBar, navigationBar, appNodes } = stripBarsFromWireframes(mobileEvent.data.wireframes)

    const nodeGroups = {
        appNodes: convertWireframesFor(appNodes, conversionContext).result || [],
        statusBarNode: makeStatusBarNode(statusBar, conversionContext),
        navBarNode: makeNavBarNode(navigationBar, conversionContext),
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
                                childNodes: [makeCSSReset(conversionContext)],
                            },
                            {
                                type: NodeType.Element,
                                tagName: 'body',
                                attributes: { style: makeBodyStyles(), 'data-rrweb-id': BODY_ID },
                                id: BODY_ID,
                                childNodes: [
                                    // in the order they should stack if they ever clash
                                    // lower is higher in the stacking context
                                    ...nodeGroups.appNodes,
                                    makeKeyboardParent(),
                                    nodeGroups.navBarNode,
                                    nodeGroups.statusBarNode,
                                ],
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

function makeCSSReset(context: ConversionContext): serializedNodeWithId {
    // we need to normalize CSS so browsers don't do unexpected things
    return {
        type: NodeType.Element,
        tagName: 'style',
        attributes: {
            type: 'text/css',
        },
        id: context.idSequence.next().value,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: `
                    body {
                      margin: unset;
                    }
                    input, button, select, textarea {
                        font: inherit;
                        margin: 0;
                        padding: 0;
                        border: 0;
                        outline: 0;
                        background: transparent;
                        padding-block: 0 !important;
                    }
                    .input:focus {
                        outline: none;
                    }
                    img {
                      border-style: none;
                    }
                `,
                id: context.idSequence.next().value,
            },
        ],
    }
}
