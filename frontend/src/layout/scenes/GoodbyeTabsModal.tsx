import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { goodbyeTabsModalLogic } from './goodbyeTabsModalLogic'

export function GoodbyeTabsModal(): JSX.Element {
    const { isOpen, tabs, backendTabsLoading } = useValues(goodbyeTabsModalLogic)
    const { dismiss } = useActions(goodbyeTabsModalLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={dismiss}
            title="Goodbye posthog tabs 🪓"
            description="They were fun, but they're a big papercut"
            width="32rem"
            footer={
                <LemonButton type="primary" onClick={dismiss} data-attr="goodbye-tabs-dismiss">
                    Got it
                </LemonButton>
            }
        >
            <div className="deprecated-space-y-2">
                {tabs.length === 0 && backendTabsLoading ? (
                    <div className="text-muted">Loading your tabs…</div>
                ) : tabs.length === 0 ? (
                    <div className="text-muted">No saved tabs to show.</div>
                ) : (
                    <>
                        <p className="text-sm text-muted m-0">
                            Here are the tabs you had open. Pinned ones are listed first.
                        </p>
                        <ul className="m-0 pl-0 list-none deprecated-space-y-1">
                            {tabs.map((tab) => (
                                <li
                                    key={tab.url}
                                    className="flex items-center gap-2 border border-border rounded px-2 py-1.5 bg-surface-primary"
                                >
                                    {tab.pinned && (
                                        <span className="text-xs uppercase tracking-wide text-tertiary">Pinned</span>
                                    )}
                                    <Link to={tab.url} className="truncate" onClick={dismiss}>
                                        {tab.title}
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
