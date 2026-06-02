import { MultiModalContentItem } from '../../../../types'
import { Scope } from '../../scope'
import { Expr } from './base'

const STRUCTURED_CONTENT_TYPES = new Set([
    'text',
    'output_text',
    'input_text',
    'function',
    'image',
    'input_image',
    'image_url',
    'file',
    'audio',
    'document',
])

export class TryParseStructuredContentExpr extends Expr {
    constructor(private readonly input: Expr) {
        super()
    }
    eval(scope: Scope): unknown {
        const value = this.input.eval(scope)
        return typeof value === 'string' ? parseStringifiedStructuredContent(value) : value
    }
}

function parseStringifiedStructuredContent(content: string): string | MultiModalContentItem[] {
    const trimmed = content.trim()
    if (!trimmed.startsWith('[')) {
        return content
    }
    try {
        const parsed = JSON.parse(trimmed)
        if (
            Array.isArray(parsed) &&
            parsed.every(
                (item) =>
                    item &&
                    typeof item === 'object' &&
                    'type' in item &&
                    typeof item.type === 'string' &&
                    STRUCTURED_CONTENT_TYPES.has(item.type)
            )
        ) {
            return parsed as MultiModalContentItem[]
        }
    } catch {
        // Not valid JSON — keep the raw string.
    }
    return content
}
