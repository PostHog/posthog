import { useActions, useValues } from 'kea'

import { IconPerson, IconPlayFilled, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { TICKET_SIDEBAR_WIDGETS, type TicketSidebarWidgetKey, ticketSidebarLogic } from './ticketSidebarLogic'

function PreviewRow({ left, right }: { left: string; right?: JSX.Element | string }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-1">
            <span className="text-muted-alt truncate">{left}</span>
            {right && <span className="shrink-0">{right}</span>}
        </div>
    )
}

/** Static miniatures of what each widget looks like in the sidebar once added. */
const WIDGET_PREVIEWS: Record<TicketSidebarWidgetKey, JSX.Element> = {
    customer: (
        <div className="flex items-center gap-2">
            <div className="size-6 shrink-0 rounded-full bg-fill-highlight-100 flex items-center justify-center">
                <IconPerson />
            </div>
            <div className="flex flex-col min-w-0">
                <span className="font-medium truncate">Merle Hedgehog</span>
                <span className="text-muted-alt truncate">merle@hedgebox.net</span>
            </div>
        </div>
    ),
    'related-groups': (
        <>
            <PreviewRow left="Hedgebox Inc." right={<LemonTag size="small">organization</LemonTag>} />
            <PreviewRow left="Marketing site" right={<LemonTag size="small">project</LemonTag>} />
        </>
    ),
    'staff-actions': (
        <>
            <PreviewRow left="Customer:" right={<span className="text-success">merle@hedgebox.net</span>} />
            <PreviewRow left="" right={<LemonTag size="small">Log in as customer</LemonTag>} />
        </>
    ),
    'ai-triage': (
        <>
            <PreviewRow
                left="Result"
                right={
                    <LemonTag size="small" type="success">
                        Resolved
                    </LemonTag>
                }
            />
            <PreviewRow left="Confidence" right="82%" />
        </>
    ),
    'session-recording': (
        <div className="h-10 rounded bg-fill-highlight-100 flex items-center justify-center">
            <IconPlayFilled className="text-lg" />
        </div>
    ),
    'recent-events': (
        <>
            <PreviewRow left="$pageview" right={<span className="text-muted-alt">2m ago</span>} />
            <PreviewRow left="file_upload_failed" right={<span className="text-muted-alt">5m ago</span>} />
        </>
    ),
    exceptions: (
        <>
            <PreviewRow
                left="Cannot read properties of undefined"
                right={
                    <LemonTag size="small" type="danger">
                        TypeError
                    </LemonTag>
                }
            />
            <PreviewRow left="Failed to fetch" right={<span className="text-muted-alt">1h ago</span>} />
        </>
    ),
    'previous-tickets': (
        <>
            <PreviewRow
                left="#12 File uploads failing"
                right={
                    <LemonTag size="small" type="success">
                        Resolved
                    </LemonTag>
                }
            />
            <PreviewRow left="#8 How do I share a folder?" right={<LemonTag size="small">Open</LemonTag>} />
        </>
    ),
    activity: (
        <>
            <PreviewRow left="● Status changed to open" right={<span className="text-muted-alt">2m ago</span>} />
            <PreviewRow left="● Assigned to Christian" right={<span className="text-muted-alt">1h ago</span>} />
        </>
    ),
}

export function AddWidgetsBlock({ availableWidgets }: { availableWidgets: TicketSidebarWidgetKey[] }): JSX.Element {
    const { hiddenWidgets, widgetsModalOpen } = useValues(ticketSidebarLogic)
    const { setWidgetVisible, setWidgetsModalOpen } = useActions(ticketSidebarLogic)

    const widgets = TICKET_SIDEBAR_WIDGETS.filter((widget) => availableWidgets.includes(widget.key))

    return (
        <>
            <LemonButton
                fullWidth
                center
                type="secondary"
                icon={<IconPlus />}
                onClick={() => setWidgetsModalOpen(true)}
                aria-label="Add widgets"
                tooltip="Add widgets"
                className="border-dashed"
            />
            <LemonModal
                isOpen={widgetsModalOpen}
                onClose={() => setWidgetsModalOpen(false)}
                title="Widgets"
                description="Choose which widgets to show in the ticket sidebar."
                width={560}
            >
                <div className="grid grid-cols-2 gap-2">
                    {widgets.map((widget) => (
                        <LemonCheckbox
                            key={widget.key}
                            bordered
                            fullWidth
                            checked={!hiddenWidgets.includes(widget.key)}
                            onChange={(checked) => setWidgetVisible(widget.key, checked)}
                            labelClassName="flex-1 min-w-0"
                            label={
                                <div className="flex flex-col gap-1.5 py-1 min-w-0">
                                    <span className="text-xs font-semibold">{widget.label}</span>
                                    <div className="space-y-1 rounded border bg-surface-primary p-2 text-xxs pointer-events-none select-none">
                                        {WIDGET_PREVIEWS[widget.key]}
                                    </div>
                                    <span className="text-xxs text-muted font-normal">{widget.description}</span>
                                </div>
                            }
                        />
                    ))}
                </div>
            </LemonModal>
        </>
    )
}
