import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

function derivedScopeLabel(url: string): string {
    try {
        const parsed = new URL(url)
        const path = parsed.pathname.replace(/\/+$/, '') || '/'
        if (path === '/') {
            return 'the whole site'
        }
        return `${parsed.hostname}${path} and pages under it`
    } catch {
        return 'pages at this URL'
    }
}

export function CrawlConfigFields({ crawlMode, url }: { crawlMode: string; url: string }): JSX.Element | null {
    if (crawlMode === 'single') {
        return null
    }

    const isSameOrigin = crawlMode === 'same_origin'

    return (
        <>
            {isSameOrigin && url.trim() && (
                <p className="text-xs text-muted mt-0">
                    Will index <strong>{derivedScopeLabel(url)}</strong>. Use "Skip paths" below to exclude sections.
                </p>
            )}
            <LemonField
                name="exclude_globs"
                label="Skip paths"
                info="URL path patterns to skip (fnmatch). One per line or comma-separated. E.g. /docs/internal/*"
            >
                <LemonTextArea minRows={2} placeholder="/docs/private/*" />
            </LemonField>
            <div className="flex gap-2">
                <LemonField name="max_pages" label="Max pages" className="flex-1">
                    <LemonInput type="number" min={1} max={500} />
                </LemonField>
                {isSameOrigin && (
                    <LemonField name="max_depth" label="Max depth" className="flex-1">
                        <LemonInput type="number" min={0} max={5} />
                    </LemonField>
                )}
            </div>
            <LemonCollapse
                panels={[
                    {
                        key: 'advanced',
                        header: 'Advanced: override include scope',
                        content: (
                            <LemonField
                                name="include_globs"
                                label="Include globs"
                                info="Override the auto-derived scope. URL path patterns to include (fnmatch). One per line or comma-separated. Empty = scope to Entry URL path."
                            >
                                <LemonTextArea
                                    minRows={2}
                                    placeholder={
                                        isSameOrigin
                                            ? 'Leave empty to use entry URL path as scope'
                                            : '/docs/*\n/handbook/*'
                                    }
                                />
                            </LemonField>
                        ),
                    },
                ]}
                size="small"
                embedded
            />
        </>
    )
}
