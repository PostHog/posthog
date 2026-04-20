import '@react-email/editor/themes/default.css'
import '@react-email/editor/styles/slash-command.css'
import '@react-email/editor/styles/bubble-menu.css'

import { EmailEditor, type EmailEditorRef } from '@react-email/editor'
import { StarterKit } from '@react-email/editor/extensions'
import { EmailTheming } from '@react-email/editor/plugins'
import { SlashCommand } from '@react-email/editor/ui'
import { forwardRef, useCallback, useImperativeHandle, useRef, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CyclotronJobTemplateSuggestionsButton } from 'lib/components/CyclotronJob/CyclotronJobTemplateSuggestions'

import type { ReactEmailDesign, ReactEmailMergeTags } from './types'

const UNSUBSCRIBE_URL_MERGE_TAG = '{{ unsubscribe_url }}'

/**
 * Custom theme with the Ubuntu font — matches the custom font we ship to the
 * Unlayer editor so switching between engines keeps visual parity.
 */
const POSTHOG_THEME = {
    fontFamily: "'Ubuntu', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Tahoma, Verdana, sans-serif",
    fontUrl: 'https://fonts.googleapis.com/css?family=Ubuntu:300,400,500,700',
}

/**
 * Shape that matches the `EditorRef.editor` API surface consumed by
 * `emailTemplaterLogic` today, so Unlayer and react-email flows can share the
 * same call sites. We only reimplement the methods the logic actually calls:
 * `loadDesign`, `exportHtml`, and `exportPlainText`.
 */
export interface ReactEmailEditorShimRef {
    editor: {
        loadDesign: (design: ReactEmailDesign | null | undefined) => void
        exportHtml: (cb: (data: { html: string; design: ReactEmailDesign }) => void) => void
        exportPlainText: (cb: (data: { text: string }) => void) => void
    } | null
}

export interface ReactEmailEditorShimProps {
    initialDesign?: ReactEmailDesign | null
    mergeTags: ReactEmailMergeTags
    onReady: () => void
    templating: 'hog' | 'liquid'
    setTemplatingEngine?: (templating: 'hog' | 'liquid') => void
}

/**
 * Wraps `@react-email/editor` with:
 * - Ubuntu font (parity with our Unlayer setup)
 * - A merge-tag dropdown (reuses `CyclotronJobTemplateSuggestionsButton`) for
 *   liquid/hog autocompletion — inserts at the current cursor position.
 * - An "Insert unsubscribe link" button that produces an `<a>` pointing at the
 *   same `{{ unsubscribe_url }}` merge tag our backend renderer already knows
 *   about.
 *
 * The component forwards a minimal `editor` handle so it can drop into the
 * same call sites that consume Unlayer's `EditorRef`.
 */
export const ReactEmailEditorShim = forwardRef<ReactEmailEditorShimRef, ReactEmailEditorShimProps>(
    function ReactEmailEditorShim({ initialDesign, mergeTags, onReady, templating, setTemplatingEngine }, ref) {
        const innerRef = useRef<EmailEditorRef>(null)
        // We need to remember the "initial load" design until the editor becomes
        // ready — the parent logic calls `loadDesign` inside `onReady`, so the
        // underlying `editor` may be null at that moment.
        const [pendingDesign, setPendingDesign] = useState<ReactEmailDesign | null | undefined>(initialDesign)

        useImperativeHandle(
            ref,
            () => ({
                editor: {
                    loadDesign: (design) => {
                        const editor = innerRef.current?.editor
                        if (editor && design) {
                            editor.commands.setContent(design as any)
                            return
                        }
                        // Defer until ready.
                        setPendingDesign(design ?? null)
                    },
                    exportHtml: (cb) => {
                        const handle = innerRef.current
                        if (!handle) {
                            return
                        }
                        void handle.getEmailHTML().then((html: string) => {
                            const design = handle.getJSON() as ReactEmailDesign
                            cb({ html, design })
                        })
                    },
                    exportPlainText: (cb) => {
                        const handle = innerRef.current
                        if (!handle) {
                            return
                        }
                        void handle.getEmailText().then((text: string) => cb({ text }))
                    },
                },
            }),
            []
        )

        const handleReady = useCallback(() => {
            const editor = innerRef.current?.editor
            if (editor && pendingDesign) {
                editor.commands.setContent(pendingDesign as any)
                setPendingDesign(undefined)
            }
            onReady()
        }, [onReady, pendingDesign])

        const insertText = useCallback((text: string) => {
            innerRef.current?.editor?.chain().focus().insertContent(text).run()
        }, [])

        const insertUnsubscribeLink = useCallback(() => {
            const editor = innerRef.current?.editor
            if (!editor) {
                return
            }
            editor
                .chain()
                .focus()
                .insertContent({
                    type: 'text',
                    text: 'Unsubscribe',
                    marks: [{ type: 'link', attrs: { href: UNSUBSCRIBE_URL_MERGE_TAG } }],
                })
                .run()
        }, [])

        // Collapse merge tags into the shape `CyclotronJobTemplateSuggestionsButton` expects.
        const mergeTagOptions = Object.entries(mergeTags).map(([key, tag]) => ({
            key,
            example: tag.value,
            description: tag.name,
        }))

        return (
            <div className="flex flex-col flex-1 min-h-0">
                <div className="flex gap-1 items-center px-2 py-1 border-b shrink-0">
                    <LemonButton size="xsmall" type="secondary" icon={<IconExternal />} onClick={insertUnsubscribeLink}>
                        Insert unsubscribe link
                    </LemonButton>
                    <CyclotronJobTemplateSuggestionsButton
                        templating={templating}
                        setTemplatingEngine={setTemplatingEngine}
                        value=""
                        onOptionSelect={(option) => insertText(option.example)}
                    />
                    {mergeTagOptions.length > 0 && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => insertText(mergeTagOptions[0].example)}
                            tooltip={`Insert ${mergeTagOptions[0].description}`}
                        >
                            Insert variable
                        </LemonButton>
                    )}
                </div>
                <div className="relative flex-1 min-h-0 overflow-auto">
                    <EmailEditor
                        ref={innerRef}
                        extensions={[StarterKit, EmailTheming]}
                        theme={POSTHOG_THEME as any}
                        onReady={handleReady}
                    >
                        <SlashCommand />
                    </EmailEditor>
                </div>
            </div>
        )
    }
)
