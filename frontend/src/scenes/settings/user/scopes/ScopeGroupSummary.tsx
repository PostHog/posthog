import { Fragment } from 'react'

import { summarizeScopesByGroup } from 'lib/scopes'

export function ScopeGroupSummary({ scopes }: { scopes: readonly string[] }): JSX.Element {
    return (
        <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
            {summarizeScopesByGroup(scopes).map(({ label, write, read }) => (
                <Fragment key={label}>
                    <span>{label}</span>
                    <span className="text-right whitespace-nowrap opacity-75">
                        {[write ? `${write} write` : null, read ? `${read} read` : null].filter(Boolean).join(' · ')}
                    </span>
                </Fragment>
            ))}
        </div>
    )
}
