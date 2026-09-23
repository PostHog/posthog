// eslint-disable-next-line import/no-cycle
import { parseTruncatedSegments } from './segmentParser'
import { TextSegment } from './types'

// Use TextDecoder so emoji and other multi-byte UTF-8 characters decode correctly
export function decodeBase64Utf8(base64String: string): string {
    const binaryString = atob(base64String)
    const bytes = new Uint8Array(binaryString.length)
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i)
    }
    return new TextDecoder('utf-8').decode(bytes)
}

export function getPlainText(segments: TextSegment[]): string {
    return segments.map((seg) => (seg.type === 'truncated' ? seg.content : seg.content)).join('')
}

// Expands gen_expandable nodes but keeps truncation markers collapsed
export function getExpandedTreeText(segments: TextSegment[]): string {
    return segments
        .map((seg) => {
            if (seg.type === 'gen_expandable' && seg.fullContent) {
                const nestedSegments = parseTruncatedSegments(seg.fullContent)
                return nestedSegments.map((nestedSeg) => nestedSeg.content).join('')
            }
            return seg.content
        })
        .join('')
}

// Returns the number of digits in the largest line number (e.g. 3 for L100, 4 for L1000)
export function calculateLineNumberPadding(text: string): number {
    let maxLineNumber = 0
    const lineMatches = text.matchAll(/^L(\d+):/gm)
    for (const match of lineMatches) {
        const lineNum = parseInt(match[1], 10)
        if (lineNum > maxLineNumber) {
            maxLineNumber = lineNum
        }
    }
    return maxLineNumber > 0 ? maxLineNumber.toString().length : 0
}
