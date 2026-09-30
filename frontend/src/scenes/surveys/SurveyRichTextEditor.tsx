import { useEffect, useRef } from 'react'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import { SupportEditor } from 'products/conversations/frontend/components/Editor'

import { SURVEY_RICH_TEXT_FORMATS, normalizeRichTextHtml } from './surveyRichText'

export function SurveyRichTextEditor({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const editorRef = useRef<RichContentEditorType | null>(null)

    // The value also changes from outside the editor, for example when the author converts from the text tab
    useEffect(() => {
        const editor = editorRef.current
        if (editor && normalizeRichTextHtml(editor.getHTML()) !== value) {
            editor.setContent(value)
        }
    }, [value])

    return (
        <SupportEditor
            formats={SURVEY_RICH_TEXT_FORMATS}
            minRows={3}
            className="mt-0"
            onCreate={(editor) => {
                editorRef.current = editor
                editor.setContent(value)
            }}
            onUpdate={() => {
                if (editorRef.current) {
                    onChange(normalizeRichTextHtml(editorRef.current.getHTML()))
                }
            }}
        />
    )
}
