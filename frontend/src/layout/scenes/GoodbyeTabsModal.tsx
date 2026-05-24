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
            title="Goodbye tabs 🪓"
            description="Tabs were a fun experiment, but they are extremely hard to get right."
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
