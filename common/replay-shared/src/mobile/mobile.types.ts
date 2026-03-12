// copied from rrweb-snapshot, not included in rrweb types
import { EventType, IncrementalSource, customEvent, removedNodeMutation } from '@posthog/rrweb-types'

export enum NodeType {
    Document = 0,
    DocumentType = 1,
    Element = 2,
    Text = 3,
    CDATA = 4,
    Comment = 5,
}

export type documentNode = {
    type: NodeType.Document
    childNodes: serializedNodeWithId[]
    compatMode?: string
}

export type documentTypeNode = {
    type: NodeType.DocumentType
    name: string
    publicId: string
    systemId: string
}

export type attributes = {
    [key: string]: string | number | true | null
}

export type elementNode = {
    type: NodeType.Element
    tagName: string
    attributes: attributes
    childNodes: serializedNodeWithId[]
    isSVG?: true
    needBlock?: boolean
    // This is a custom element or not.
    isCustom?: true
}

export type textNode = {
    type: NodeType.Text
    textContent: string
    isStyle?: true
}

export type cdataNode = {
    type: NodeType.CDATA
    textContent: ''
}

export type commentNode = {
    type: NodeType.Comment
    textContent: string
}

export type serializedNode = (documentNode | documentTypeNode | elementNode | textNode | cdataNode | commentNode) & {
    rootId?: number
    isShadowHost?: boolean
    isShadow?: boolean
}

export type serializedNodeWithId = serializedNode & { id: number }

// end copied section

export type MobileNodeType =
    | 'text'
    | 'image'
    | 'screenshot'
    | 'rectangle'
    | 'placeholder'
    | 'web_view'
    | 'input'
    | 'div'
    | 'radio_group'
    | 'status_bar'
    | 'navigation_bar'

export type MobileStyles = {
    /**
     * @description maps to CSS color. Accepts any valid CSS color value. Expects a #RGB value e.g. #000 or #000000
     */
    color?: string
    /**
     * @description maps to CSS background-color. Accepts any valid CSS color value. Expects a #RGB value e.g. #000 or #000000
     */
    backgroundColor?: string
    /**
     * @description if provided this will be used as a base64 encoded image source for the backgroundImage css property, with no other attributes it is assumed to be a PNG
     */
    backgroundImage?: string
    /**
     * @description can be used alongside the background image property to specify how the image is rendered. Accepts a subset of the valid values for CSS background-size property. If not provided (and backgroundImage is present) defaults to 'auto'
     */
    backgroundSize?: 'contain' | 'cover' | 'auto'
    /**
     * @description if borderWidth is present, then border style is assumed to be solid
     */
    borderWidth?: string | number
    /**
     * @description if borderRadius is present, then border style is assumed to be solid
     */
    borderRadius?: string | number
    /**
     * @description if borderColor is present, then border style is assumed to be solid
     */
    borderColor?: string
    /**
     * @description vertical alignment with respect to its parent
     */
    verticalAlign?: 'top' | 'bottom' | 'center'
    /**
     * @description horizontal alignment with respect to its parent
     */
    horizontalAlign?: 'left' | 'right' | 'center'
    /**
     * @description maps to CSS font-size. Accepts any valid CSS font-size value. Expects a number (treated as pixels) or a string that is a number followed by px e.g. 16px
     */
    fontSize?: string | number
    /**
     * @description maps to CSS font-family. Accepts any valid CSS font-family value.
     */
    fontFamily?: string
    /**
     * @description maps to CSS padding-left. Expects a number (treated as pixels) or a string that is a number followed by px e.g. 16px
     */
    paddingLeft?: string | number
    /**
     * @description maps to CSS padding-right. Expects a number (treated as pixels) or a string that is a number followed by px e.g. 16px
     */
    paddingRight?: string | number
    /**
     * @description maps to CSS padding-top. Expects a number (treated as pixels) or a string that is a number followed by px e.g. 16px
     */
    paddingTop?: string | number
    /**
     * @description maps to CSS padding-bottom. Expects a number (treated as pixels) or a string that is a number followed by px e.g. 16px
     */
    paddingBottom?: string | number
}

type wireframeBase = {
    id: number
    /**
     * @description x and y are the top left corner of the element, if they are present then the element is absolutely positioned, if they are not present this is equivalent to setting them to 0
     */
    x?: number
    y?: number
    /*
     * @description the width dimension of the element, either '100vw' i.e. viewport width. Or a value in pixels. You can omit the unit when specifying pixels.
     */
    width: number | '100vw'
    /*
     * @description the height dimension of the element, the only accepted units is pixels. You can omit the unit.
     */
    height: number
    childWireframes?: wireframe[]
    type: MobileNodeType
    style?: MobileStyles
}

export type wireframeInputBase = wireframeBase & {
    type: 'input'
    /**
     * @description for several attributes we technically only care about true or absent as values. They are represented as bare attributes in HTML <input disabled>. When true that attribute is added to the HTML element, when absent that attribute is not added to the HTML element. When false or absent they are not added to the element.
     */
    disabled: boolean
}

export type wireframeCheckBox = wireframeInputBase & {
    inputType: 'checkbox'
    /**
     * @description for several attributes we technically only care about true or absent as values. They are represented as bare attributes in HTML <input checked>. When true that attribute is added to the HTML element, when absent that attribute is not added to the HTML element. When false or absent they are not added to the element.
     */
    checked: boolean
    label?: string
}

export type wireframeToggle = wireframeInputBase & {
    inputType: 'toggle'
    checked: boolean
    label?: string
}

export type wireframeRadioGroup = wireframeBase & {
    type: 'radio_group'
}

export type wireframeRadio = wireframeInputBase & {
    inputType: 'radio'
    /**
     * @description for several attributes we technically only care about true or absent as values. They are represented as bare attributes in HTML <input checked>. When true that attribute is added to the HTML element, when absent that attribute is not added to the HTML element. When false or absent they are not added to the element.
     */
    checked: boolean
    label?: string
}

export type wireframeInput = wireframeInputBase & {
    inputType: 'text' | 'password' | 'email' | 'number' | 'search' | 'tel' | 'url'
    value?: string
}

export type wireframeSelect = wireframeInputBase & {
    inputType: 'select'
    value?: string
    options?: string[]
}

export type wireframeTextArea = wireframeInputBase & {
    inputType: 'text_area'
    value?: string
}

export type wireframeButton = wireframeInputBase & {
    inputType: 'button'
    /**
     * @description this is the text that is displayed on the button, if not sent then you must send childNodes with the button content
     */
    value?: string
}

export type wireframeProgress = wireframeInputBase & {
    inputType: 'progress'
    /**
     * @description This attribute specifies how much of the task that has been completed. It must be a valid floating point number between 0 and max, or between 0 and 1 if max is omitted. If there is no value attribute, the progress bar is indeterminate; this indicates that an activity is ongoing with no indication of how long it is expected to take. When bar style is rating this is the number of filled stars.
     */
    value?: number
    /**
     * @description The max attribute, if present, must have a value greater than 0 and be a valid floating point number. The default value is 1. When bar style is rating this is the number of stars.
     */
    max?: number
    style?: MobileStyles & {
        bar: 'horizontal' | 'circular' | 'rating'
    }
}

// these are grouped as a type so that we can easily use them as function parameters
export type wireframeInputComponent =
    | wireframeCheckBox
    | wireframeRadio
    | wireframeInput
    | wireframeSelect
    | wireframeTextArea
    | wireframeButton
    | wireframeProgress
    | wireframeToggle

export type wireframeText = wireframeBase & {
    type: 'text'
    text: string
}

export type wireframeImage = wireframeBase & {
    type: 'image'
    /**
     * @description this will be used as base64 encoded image source, with no other attributes it is assumed to be a PNG, if omitted a placeholder is rendered
     */
    base64?: string
}

/**
 * @description a screenshot behaves exactly like an image, but it is expected to be a screenshot of the screen at the time of the event, when sent as a mutation it must always attached to the root of the playback, when sent as an initial snapshot it must be sent as the first or only snapshot so that it attaches to the body of the playback
 */
export type wireframeScreenshot = wireframeImage & {
    type: 'screenshot'
}

export type wireframeRectangle = wireframeBase & {
    type: 'rectangle'
}

export type wireframeWebView = wireframeBase & {
    type: 'web_view'
    url?: string
}

export type wireframePlaceholder = wireframeBase & {
    type: 'placeholder'
    label?: string
}

export type wireframeDiv = wireframeBase & {
    /*
     * @description this is the default type, if no type is specified then it is assumed to be a div
     */
    type: 'div'
}

/**
 * @description the status bar respects styling and positioning, but it is expected to be at the top of the screen with limited styling and no child elements
 */
export type wireframeStatusBar = wireframeBase & {
    type: 'status_bar'
}

/**
 * @description the navigation bar respects styling and positioning, but it is expected to be at the bottom of the screen with limited styling and no child elements
 */
export type wireframeNavigationBar = wireframeBase & {
    type: 'navigation_bar'
}

export type wireframe =
    | wireframeText
    | wireframeImage
    | wireframeScreenshot
    | wireframeRectangle
    | wireframeDiv
    | wireframeInputComponent
    | wireframeRadioGroup
    | wireframeWebView
    | wireframePlaceholder
    | wireframeStatusBar
    | wireframeNavigationBar

// the rrweb full snapshot event type, but it contains wireframes not html
export type fullSnapshotEvent = {
    type: EventType.FullSnapshot
    data: {
        /**
         * @description This mimics the RRWeb full snapshot event type, except instead of reporting a serialized DOM it reports a wireframe representation of the screen.
         */
        wireframes: wireframe[]
        initialOffset: {
            top: number
            left: number
        }
    }
}

export type incrementalSnapshotEvent =
    | {
          type: EventType.IncrementalSnapshot
          data: any // keeps a loose incremental type so that we can accept any rrweb incremental snapshot event type
      }
    | MobileIncrementalSnapshotEvent

export type MobileNodeMutation = {
    parentId: number
    wireframe: wireframe
}

export type MobileNodeMutationData = {
    source: IncrementalSource.Mutation
    /**
     * @description An update is implemented as a remove and then an add, so the updates array contains the ID of the removed node and the wireframe for the added node
     */
    updates?: MobileNodeMutation[]
    adds?: MobileNodeMutation[]
    /**
     * @description A mobile remove is identical to a web remove
     */
    removes?: removedNodeMutation[]
}

export type MobileIncrementalSnapshotEvent = {
    type: EventType.IncrementalSnapshot
    /**
     * @description This sits alongside the RRWeb incremental snapshot event type, mobile replay can send any of the RRWeb incremental snapshot event types, which will be passed unchanged to the player - for example to send touch events. removed node mutations are passed unchanged to the player.
     */
    data: MobileNodeMutationData
}

export type metaEvent = {
    type: EventType.Meta
    data: {
        href?: string
        width: number
        height: number
    }
}

// this is a custom event _but_ rrweb only types tag as string, and we want to be more specific
export type keyboardEvent = {
    type: EventType.Custom
    data: {
        tag: 'keyboard'
        payload:
            | {
                  open: true
                  styles?: MobileStyles
                  /**
                   * @description x and y are the top left corner of the element, if they are present then the element is absolutely positioned, if they are not present then the keyboard is at the bottom of the screen
                   */
                  x?: number
                  y?: number
                  /*
                   * @description the height dimension of the keyboard, the only accepted units is pixels. You can omit the unit.
                   */
                  height: number
                  /*
                   * @description the width dimension of the keyboard, the only accepted units is pixels. You can omit the unit. If not present defaults to width of the viewport
                   */
                  width?: number
              }
            | { open: false }
    }
}

export type mobileEvent = fullSnapshotEvent | metaEvent | customEvent | incrementalSnapshotEvent | keyboardEvent

export type mobileEventWithTime = mobileEvent & {
    timestamp: number
    delay?: number
}
