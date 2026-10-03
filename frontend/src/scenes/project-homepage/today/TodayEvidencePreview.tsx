import { Text, cn } from '@posthog/quill'

import { TodayCodeExcerpt } from './TodayCodeExcerpt'
import { TodayChosenExcerpt, TodaySignalPreview } from './todaySignalPreview'

/** The small piece of an evidence row's own data that shows in place when the row opens. */
export function TodayEvidencePreview({
    preview,
    chosen,
}: {
    preview: TodaySignalPreview
    chosen: TodayChosenExcerpt | 'loading' | null
}): JSX.Element | null {
    const code = preview.code.length > 0 && chosen ? <TodayCodeExcerpt file={preview.code[0]} chosen={chosen} /> : null
    const block =
        preview.block.length > 0 ? (
            <pre
                className="TodayCode TodayCode__body m-0 rounded-md border px-3 py-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap"
                data-attr="today-report-signal-block"
            >
                {preview.block.map((line, index) => (
                    <div key={index} className={cn(line.quiet && 'text-muted-foreground')}>
                        {line.text}
                    </div>
                ))}
            </pre>
        ) : null
    const text = preview.text ? (
        <Text size="sm" render={<p />} className="TodaySignalReading__text leading-relaxed text-pretty">
            {preview.text}
        </Text>
    ) : null

    if (!code && !block && !text) {
        return null
    }
    return (
        <>
            {code}
            {block}
            {text}
        </>
    )
}
