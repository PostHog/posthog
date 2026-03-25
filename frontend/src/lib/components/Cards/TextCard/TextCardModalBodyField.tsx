import { lazy, Suspense, useMemo } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

export interface TextCardModalBodyFieldProps {
    shouldUseLegacyMarkdownEditor: boolean
    value: string | undefined
    onChange: (value: string) => void
}

// useMemo defers lazy() until mount so only one chunk loads per mode, and Jest can spyOn(React.lazy)
// without jest.resetModules() (which duplicates React and breaks hooks in children like Spinner).
export function TextCardModalBodyField({
    shouldUseLegacyMarkdownEditor,
    value,
    onChange,
}: TextCardModalBodyFieldProps): JSX.Element {
    const LazyEditor = useMemo(() => {
        if (shouldUseLegacyMarkdownEditor) {
            return lazy(() =>
                import('lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown').then((m) => ({
                    default: m.LemonTextAreaMarkdown,
                }))
            )
        }
        return lazy(() =>
            import('lib/components/Cards/TextCard/TextCardMarkdownEditor').then((m) => ({
                default: m.TextCardMarkdownEditor,
            }))
        )
    }, [shouldUseLegacyMarkdownEditor])

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
                <LazyEditor
                    value={value}
                    onChange={onChange}
                    maxLength={4000}
                    minRows={8}
                    maxRows={36}
                    data-attr="text-card-edit-area"
                />
            ) : (
                <LazyEditor value={value} onChange={onChange} minRows={8} maxRows={36} />
            )}
        </Suspense>
    )
}
