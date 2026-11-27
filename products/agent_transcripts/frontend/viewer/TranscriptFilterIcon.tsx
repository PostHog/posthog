import type { TranscriptFilter } from './transcriptViewerLogic'

const PATHS: Record<TranscriptFilter, string> = {
    focus: 'M5 2H2v3m9-3h3v3M2 11v3h3m9-3v3h-3M8 6v4M6 8h4',
    all: 'M5 4h9M5 8h9M5 12h9M2 4h.1M2 8h.1M2 12h.1',
    message: 'M3 3h10v7H8l-4 3v-3H3z',
    user: 'M8 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Zm-5 5a5 4 0 0 1 10 0',
    thinking: 'M6 11c0-2-2-2-2-5a4 4 0 0 1 8 0c0 3-2 3-2 5M6 11h4m-3 3h2',
    tool: 'M2 3h12v10H2zm3 3 2 2-2 2m4 0h2',
    web: 'M14 8A6 6 0 1 1 2 8a6 6 0 0 1 12 0ZM2 8h12M8 2a12 12 0 0 1 0 12 12 12 0 0 1 0-12Z',
    system: 'M8 2 3 4v4c0 3 2 5 5 6 3-1 5-3 5-6V4zm0 3v4m0 2h.1',
}

export function TranscriptFilterIcon({ filter }: { filter: TranscriptFilter }): JSX.Element {
    return (
        <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.25"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
        >
            <path d={PATHS[filter]} />
        </svg>
    )
}
