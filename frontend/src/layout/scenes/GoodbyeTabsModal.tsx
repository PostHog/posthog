import { useActions, useValues } from 'kea'

import { IconCopy, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { goodbyeTabsModalLogic } from './goodbyeTabsModalLogic'

export function GoodbyeTabsModal(): JSX.Element {
    const { isOpen, tabs, backendTabsLoading } = useValues(goodbyeTabsModalLogic)
    const { dismiss } = useActions(goodbyeTabsModalLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={dismiss}
            title="Goodbye tabs 😔"
            description="Tabs were a fun experiment, but doing them well across an app this size is genuinely hard; your browser already nails it."
            width="32rem"
            footer={
                <LemonButton type="primary" onClick={dismiss} data-attr="goodbye-tabs-dismiss">
                    Got it
                </LemonButton>
            }
        >
            <div className="deprecated-space-y-2">
                <div className="text-sm deprecated-space-y-2">
                    <p className="m-0">
                        Users expected each tab to fully restore on switch: every input, every scroll position, every
                        bit of in-memory state. Solving that across an app this size is a huge undertaking, and it
                        competes with the ongoing work to reduce memory usage.
                    </p>
                    <p className="m-0">
                        Tabs also overrode normal browser behavior: right-click menus on links were replaced with a
                        custom contextual menu, and links with <code>target="_blank"</code> opened as scene tabs instead
                        of real browser tabs. Rather than ship a subpar version of something browsers already do
                        perfectly, we're handing it back to them.
                    </p>
                    <p className="m-0">
                        See the{' '}
                        <Link to="https://github.com/PostHog/posthog/issues/59856" target="_blank">
                            GitHub issue
                        </Link>{' '}
                        to learn more and share feedback on this decision.
                    </p>
                </div>
                <hr className="mt-2 mb-3 border-border" />
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
                                    <Link to={tab.url} className="truncate flex-1 min-w-0" onClick={dismiss}>
                                        {tab.title}
                                    </Link>
                                    {tab.pinned && (
                                        <span className="flex items-center gap-1 text-xs uppercase tracking-wide text-tertiary shrink-0">
                                            <IconPinFilled className="text-sm" />
                                            Pinned
                                        </span>
                                    )}
                                    <LemonButton
                                        icon={<IconCopy />}
                                        size="small"
                                        onClick={() =>
                                            void copyToClipboard(document.location.origin + tab.url, 'tab link')
                                        }
                                        tooltip="Copy link"
                                        data-attr="goodbye-tabs-copy-link"
                                    />
                                </li>
                            ))}
                        </ul>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
