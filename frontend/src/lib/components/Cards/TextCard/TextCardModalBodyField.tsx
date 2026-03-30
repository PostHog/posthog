import { lazy, Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

export interface TextCardModalBodyFieldProps {
    shouldUseLegacyMarkdownEditor: boolean
    value: string | undefined
    onChange: (value: string) => void
}

const LazyLegacyMarkdownEditor = lazy(() =>
    import('lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown').then((m) => ({
        default: m.LemonTextAreaMarkdown,
    }))
)

const LazyRichMarkdownEditor = lazy(() =>
    import('lib/components/Cards/TextCard/TextCardMarkdownEditor').then((m) => ({
        default: m.TextCardMarkdownEditor,
    }))
)

export function TextCardModalBodyField({
    shouldUseLegacyMarkdownEditor,
    value,
    onChange,
}: TextCardModalBodyFieldProps): JSX.Element {
    return (
        <Suspense
            fallback={
                <div
                    className="flex min-h-[12rem] w-full items-center justify-center rounded border border-primary bg-surface-secondary"
                    aria-busy
                    data-attr="text-card-editor-suspense-fallback"
                >
                    <Spinner className="text-2xl" />
                </div>
            }
        >
            {shouldUseLegacyMarkdownEditor ? (
                <LazyLegacyMarkdownEditor
                    value={value}
                    onChange={onChange}
                    maxLength={4000}
                    minRows={8}
                    maxRows={36}
                    data-attr="text-card-edit-area"
                />
            ) : (
                <LazyRichMarkdownEditor value={value} onChange={onChange} minRows={8} maxRows={36} />
            )}
        </Suspense>
    )
}
