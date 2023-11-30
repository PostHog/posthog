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

export type MobileNodeType = 'text' | 'image' | 'rectangle' | 'div'

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

export type wireframeText = wireframeBase & {
    type: 'text'
    text: string
}

export type wireframeImage = wireframeBase & {
    type: 'image'
    /**
     * @description this will be used as base64 encoded image source, with no other attributes it is assumed to be a PNG
     */
    base64: string
}

export type wireframeRectangle = wireframeBase & {
    type: 'rectangle'
}

export type wireframeDiv = wireframeBase & {
    /*
     * @description this is the default type, if no type is specified then it is assumed to be a div
     */
    type: 'div'
}

export type wireframe = wireframeText | wireframeImage | wireframeRectangle | wireframeDiv

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

export type metaEvent = {
    type: EventType.Meta
    data: {
        href?: string
        width: number
        height: number
    }
}

export type mobileEvent = fullSnapshotEvent | metaEvent | customEvent

export type mobileEventWithTime = mobileEvent & {
    timestamp: number
    delay?: number
}
