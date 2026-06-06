import type { JSONContent } from '@tiptap/core'
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import { Color } from '@tiptap/extension-color'
import { Image } from '@tiptap/extension-image'
import { Link } from '@tiptap/extension-link'
import { TextAlign } from '@tiptap/extension-text-align'
import { TextStyle } from '@tiptap/extension-text-style'
import { Underline } from '@tiptap/extension-underline'
import { generateHTML } from '@tiptap/html'
import StarterKit from '@tiptap/starter-kit'
import { toHtml } from 'hast-util-to-html'
import { decode } from 'he'
import { common, createLowlight } from 'lowlight'

import { ProductTourStep, ProductTourStepTranslation } from '~/types'

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
    TextAlign.configure({
        types: ['heading', 'paragraph'],
    }),
    TextStyle,
    Color,
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
export function prepareStepForRender(step: ProductTourStep): ProductTourStep {
    return {
        ...step,
        contentHtml: step.content ? generateStepHtml(step.content) : undefined,
        ...(step.translations
            ? {
                  translations: generateTranslationsHtml(step.translations),
              }
            : {}),
    }
}

/**
 * Prepares multiple steps for rendering by adding pre-computed contentHtml to each.
 */
export function prepareStepsForRender(steps: ProductTourStep[]): ProductTourStep[] {
    return steps.map(prepareStepForRender)
}

export function generateTranslationsHtml(
    translations: Record<string, ProductTourStepTranslation>
): Record<string, ProductTourStepTranslation> {
    return Object.fromEntries(
        Object.entries(translations).map(([lang, t]) => [
            lang,
            { ...t, contentHtml: t.content ? generateStepHtml(t.content) : undefined },
        ])
    )
}
