// copied from rrweb-snapshot, not included in rrweb types
import { customEvent, EventType } from '@rrweb/types'

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
    | 'rectangle'
    | 'placeholder'
    | 'web_view'
    | 'input'
    | 'div'
    | 'radio_group'

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
}

type wireframeBase = {
    id: number
    /**
     * @description x and y are the top left corner of the element, if they are present then the element is absolutely positioned, if they are not present this is equivalent to setting them to 0
     */
    x: number
    y: number
    /*
     * @description width and height are the dimensions of the element, the only accepted units is pixels. You can omit the unit.
     */
    width: number
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
     * @description This attribute specifies how much of the task that has been completed. It must be a valid floating point number between 0 and max, or between 0 and 1 if max is omitted. If there is no value attribute, the progress bar is indeterminate; this indicates that an activity is ongoing with no indication of how long it is expected to take.
     */
    value?: number
    /**
     * @description The max attribute, if present, must have a value greater than 0 and be a valid floating point number. The default value is 1.
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

export type wireframe =
    | wireframeText
    | wireframeImage
    | wireframeRectangle
    | wireframeDiv
    | wireframeInputComponent
    | wireframeRadioGroup
    | wireframeWebView
    | wireframePlaceholder

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

export type incrementalSnapshotEvent = {
    type: EventType.IncrementalSnapshot
    data: any // TODO: this will change as we implement incremental snapshots
}

export type metaEvent = {
    type: EventType.Meta
    data: {
        href?: string
        width: number
        height: number
    }
}

export type mobileEvent = fullSnapshotEvent | metaEvent | customEvent | incrementalSnapshotEvent

export type mobileEventWithTime = mobileEvent & {
    timestamp: number
    delay?: number
}
