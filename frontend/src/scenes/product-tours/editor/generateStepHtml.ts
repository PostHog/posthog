import type { JSONContent } from '@tiptap/core'
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import { Image } from '@tiptap/extension-image'
import { Link } from '@tiptap/extension-link'
import { Underline } from '@tiptap/extension-underline'
import { generateHTML } from '@tiptap/html'
import StarterKit from '@tiptap/starter-kit'
import { toHtml } from 'hast-util-to-html'
import { decode } from 'he'
import { common, createLowlight } from 'lowlight'

import { EmbedExtension } from './EmbedExtension'

const lowlight = createLowlight(common)
lowlight.register('plaintext', () => ({ contains: [] }))

function highlightCodeBlocks(html: string): string {
    return html.replace(
        /<pre[^>]*><code[^>]*class="language-(\w+)"[^>]*>([\s\S]*?)<\/code><\/pre>/gi,
        (match, lang, code) => {
            try {
                const decoded = decode(code)

                const result = lowlight.registered(lang)
                    ? lowlight.highlight(lang, decoded)
                    : lowlight.highlightAuto(decoded)

                return `<pre><code class="language-${lang}">${toHtml(result)}</code></pre>`
            } catch {
                return match
            }
        }
    )
}

/**
 * Extensions used for HTML generation.
 * These must match the extensions used in StepContentEditor,
 * minus the editor-only extensions (Placeholder, SlashCommand).
 */
const htmlExtensions = [
    StarterKit.configure({
        heading: {
            levels: [1, 2, 3],
        },
        codeBlock: false,
    }),
    CodeBlockLowlight.configure({ lowlight }),
    Link.configure({
        openOnClick: false,
        HTMLAttributes: {
            class: 'ph-tour-link',
            target: '_blank',
            rel: 'noopener noreferrer',
        },
    }),
    Image.configure({
        HTMLAttributes: {
            class: 'ph-tour-image',
        },
    }),
    Underline,
    EmbedExtension,
]

/**
 * Generates static HTML from TipTap JSONContent.
 * Used to pre-compute HTML for SDK consumption when saving product tour steps.
 *
 * @param content - TipTap JSONContent from the editor
 * @returns HTML string ready for SDK to render
 */
export function generateStepHtml(content: JSONContent | null): string {
    if (!content) {
        return ''
    }

    try {
        const html = generateHTML(content, htmlExtensions)
        return highlightCodeBlocks(html)
    } catch (error) {
        console.error('Failed to generate step HTML:', error)
        return ''
    }
}

/**
 * Prepares a step for rendering by adding pre-computed contentHtml.
 * Use this when passing steps to renderProductTourPreview or the SDK.
 */
export function prepareStepForRender<T extends { content?: Record<string, any> | null }>(
    step: T
): T & { contentHtml?: string } {
    return {
        ...step,
        contentHtml: step.content ? generateStepHtml(step.content) : undefined,
    }
}

/**
 * Prepares multiple steps for rendering by adding pre-computed contentHtml to each.
 */
export function prepareStepsForRender<T extends { content?: Record<string, any> | null }>(
    steps: T[]
): (T & { contentHtml?: string })[] {
    return steps.map(prepareStepForRender)
}
