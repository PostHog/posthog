import { Fragment } from 'react'

const SEARCH_SYNTAX: { syntax: string; meaning: string }[] = [
    { syntax: '+name', meaning: 'The model and everything it depends on' },
    { syntax: 'name+', meaning: 'The model and everything that depends on it' },
    { syntax: '+name+', meaning: 'Both sides' },
]

/**
 * Tooltip body for the lineage search syntax, shared by every surface that accepts it.
 *
 * Tooltips paint an inverted surface, so the chips borrow the surrounding foreground rather than
 * a themed background token, which would resolve to the tooltip's own color and disappear.
 */
export const SEARCH_SYNTAX_HELP = (
    <div className="flex flex-col gap-2 max-w-72">
        <p className="m-0">Type a name to match models.</p>
        <p className="m-0">Add a plus to follow lineage:</p>
        <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 items-baseline">
            {SEARCH_SYNTAX.map(({ syntax, meaning }) => (
                <Fragment key={syntax}>
                    <code className="rounded border border-current/40 px-1 text-xs whitespace-nowrap">{syntax}</code>
                    <span>{meaning}</span>
                </Fragment>
            ))}
        </div>
    </div>
)
