/**
 * Type definitions for text view parsing
 */

export interface TextSegment {
    type: 'text' | 'truncated' | 'gen_expandable' | 'tools_expandable'
    content: string
    fullContent?: string
    charCount?: number
    eventId?: string
}

export interface TextPart {
    type: 'text' | 'url'
    content: string
}

export interface EventLinkPart {
    type: 'event_link'
    eventId: string
    displayText: string
}

/**
 * Internal types for parsing segment markers
 */
export type SegmentMatch =
    | {
          index: number
          length: number
          type: 'truncated'
          data: { encodedContent: string; charCount: number }
      }
    | {
          index: number
          length: number
          type: 'gen_expandable'
          data: { eventId: string; displayText: string; encodedContent: string }
      }
    | {
          index: number
          length: number
          type: 'tools_expandable'
          data: { displayText: string; encodedContent: string }
      }

/**
 * Internal types for parsing URL and event link markers
 */
export type UrlMatch =
    | {
          index: number
          length: number
          type: 'url'
          data: { content: string }
      }
    | {
          index: number
          length: number
          type: 'event_link'
          data: { eventId: string; displayText: string }
      }
