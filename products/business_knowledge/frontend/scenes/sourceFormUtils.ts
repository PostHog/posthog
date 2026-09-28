import type { RefreshIntervalValue } from '../api'
import type { KnowledgeSourceApi } from '../generated/api.schemas'

export type KnowledgeSource = KnowledgeSourceApi
export type CrawlMode = 'single' | 'sitemap' | 'same_origin' | 'github_repo'

export interface TextSourceFormValues {
    name: string
    text: string
    always_include: boolean
}

export interface UrlSourceFormValues {
    name: string
    url: string
    crawl_mode: CrawlMode
    // Comma/newline-separated globs — split server-side. Keeping the form
    // state as a plain string is much easier than a list-of-inputs widget.
    include_globs: string
    exclude_globs: string
    max_pages: number
    max_depth: number
    // Background auto-refresh cadence, sent on both create and edit.
    refresh_interval: RefreshIntervalValue
    always_include: boolean
}

export const MAX_TEXT_BYTES = 1_000_000

export const DEFAULT_URL_SOURCE_FORM: UrlSourceFormValues = {
    name: '',
    url: '',
    crawl_mode: 'single',
    include_globs: '',
    exclude_globs: '',
    max_pages: 50,
    max_depth: 2,
    refresh_interval: 'manual',
    always_include: false,
}

export function validateText({ name, text }: TextSourceFormValues): {
    name: string | undefined
    text: string | undefined
} {
    return {
        name: !name.trim() ? 'Give the source a short name' : undefined,
        text: !text.trim()
            ? 'Paste some content'
            : new Blob([text]).size > MAX_TEXT_BYTES
              ? 'Text exceeds the 1 MB cap. Split it into smaller sources'
              : undefined,
    }
}

export function validateUrl({ name, url, max_pages }: UrlSourceFormValues): {
    name: string | undefined
    url: string | undefined
    max_pages: string | undefined
} {
    let urlError: string | undefined
    if (!url.trim()) {
        urlError = 'Paste a public HTTPS URL'
    } else {
        try {
            const parsed = new URL(url)
            if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
                urlError = 'Only http(s) URLs are allowed'
            }
        } catch {
            urlError = 'Not a valid URL'
        }
    }
    return {
        name: !name.trim() ? 'Give the source a short name' : undefined,
        url: urlError,
        max_pages: max_pages < 1 || max_pages > 500 ? 'max_pages must be between 1 and 500' : undefined,
    }
}

export function splitGlobs(raw: string): string[] {
    return raw
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean)
}

export function editUrlSourceValuesFromSource(source: KnowledgeSource): UrlSourceFormValues {
    const cfg = (source.crawl_config || {}) as {
        include_globs?: string[]
        exclude_globs?: string[]
        max_pages?: number
        max_depth?: number
    }
    return {
        name: source.name,
        url: source.source_url,
        crawl_mode: (source.crawl_mode || 'single') as CrawlMode,
        include_globs: (cfg.include_globs || []).join('\n'),
        exclude_globs: (cfg.exclude_globs || []).join('\n'),
        max_pages: cfg.max_pages ?? 50,
        max_depth: cfg.max_depth ?? 2,
        refresh_interval: (source.refresh_interval || 'manual') as RefreshIntervalValue,
        always_include: source.always_include ?? false,
    }
}
