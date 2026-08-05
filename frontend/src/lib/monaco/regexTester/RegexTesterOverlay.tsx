import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { RE2_DOCS_LINK } from 'lib/utils/regexp'

import { RegexTestMatch, regexTesterLogic } from './regexTesterLogic'

function highlightMatches(value: string, matches: RegexTestMatch[]): JSX.Element {
    const segments: JSX.Element[] = []
    let cursor = 0

    for (const [index, match] of matches.entries()) {
        if (match.start > cursor) {
            segments.push(<span key={`before-${index}`}>{value.slice(cursor, match.start)}</span>)
        }
        segments.push(
            <mark key={`match-${index}`} className="bg-highlight text-default rounded px-0.5">
                {value.slice(match.start, match.end)}
            </mark>
        )
        cursor = match.end
    }
    if (cursor < value.length) {
        segments.push(<span key="after">{value.slice(cursor)}</span>)
    }

    return <>{segments}</>
}

export function RegexTesterOverlay({ logicKey, onClose }: { logicKey: string; onClose: () => void }): JSX.Element {
    const { pattern, testString, matches, patternError } = useValues(regexTesterLogic({ logicKey }))
    const { setTestString } = useActions(regexTesterLogic({ logicKey }))

    const firstMatchGroups = matches[0]?.groups ?? []

    return (
        <div
            className="flex flex-col gap-2 w-[24rem]"
            onKeyDown={(event) => {
                if (event.key === 'Escape') {
                    onClose()
                }
            }}
        >
            <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">Test this regex</span>
                <Link to={RE2_DOCS_LINK} target="_blank" className="text-xs">
                    RE2 syntax
                </Link>
            </div>
            <code className="text-xs break-all bg-fill-highlight-50 rounded px-1 py-0.5">{pattern}</code>
            {patternError ? (
                <LemonBanner type="warning" hideIcon>
                    {patternError}
                </LemonBanner>
            ) : (
                <>
                    <LemonTextArea
                        value={testString}
                        onChange={setTestString}
                        placeholder="Paste a value to test, like https://posthog.com/blog/2024/hello"
                        minRows={2}
                        maxRows={4}
                    />
                    {testString ? (
                        <>
                            <div className="text-xs text-secondary">
                                {matches.length === 0
                                    ? 'No matches'
                                    : matches.length === 1
                                      ? '1 match'
                                      : `${matches.length} matches`}
                            </div>
                            {matches.length > 0 && (
                                <div className="text-xs font-mono break-all whitespace-pre-wrap max-h-32 overflow-y-auto">
                                    {highlightMatches(testString, matches)}
                                </div>
                            )}
                            {firstMatchGroups.length > 0 && (
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-xs text-secondary">Capture groups in the first match</span>
                                    {firstMatchGroups.map((group, index) => (
                                        <div key={index} className="text-xs font-mono break-all">
                                            <span className="text-secondary">{index + 1}: </span>
                                            {group === null ? <span className="text-secondary">no match</span> : group}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </>
                    ) : null}
                </>
            )}
        </div>
    )
}
