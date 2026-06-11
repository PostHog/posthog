import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

export function CrawlConfigFields({ crawlMode }: { crawlMode: string }): JSX.Element | null {
    if (crawlMode === 'single') {
        return null
    }
    return (
        <>
            <LemonField
                name="include_globs"
                label="Include globs"
                info="URL path patterns to include. One per line or comma-separated. Empty = include everything."
            >
                <LemonTextArea minRows={2} placeholder={'/docs/*\n/handbook/*'} />
            </LemonField>
            <LemonField
                name="exclude_globs"
                label="Exclude globs"
                info="URL path patterns to exclude. Applied after include."
            >
                <LemonTextArea minRows={2} placeholder="/docs/private/*" />
            </LemonField>
            <div className="flex gap-2">
                <LemonField name="max_pages" label="Max pages" className="flex-1">
                    <LemonInput type="number" min={1} max={500} />
                </LemonField>
                {crawlMode === 'same_origin' && (
                    <LemonField name="max_depth" label="Max depth" className="flex-1">
                        <LemonInput type="number" min={0} max={5} />
                    </LemonField>
                )}
            </div>
        </>
    )
}
