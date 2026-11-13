import { router } from 'kea-router'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Heading,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AddSavedInsightsToDashboard } from 'products/product_analytics/frontend/insights/savedInsights/AddSavedInsightsToDashboard'

import { AddInsightCreateOption } from './addInsightToDashboardCreateOptions'

export function QuillAddInsightToDashboardModal({
    isOpen,
    onClose,
    onCreateClicked,
    quickCreate,
    moreCreate,
}: {
    isOpen: boolean
    onClose: () => void
    onCreateClicked: (insightType: string) => void
    quickCreate: AddInsightCreateOption[]
    moreCreate: AddInsightCreateOption[]
}): JSX.Element {
    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent size="wide" className="max-w-215" data-attr="add-insight-to-dashboard-modal">
                <DialogHeader>
                    <DialogTitle>Add insight to dashboard</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-wrap items-center gap-2">
                            <div className="flex min-w-0 flex-col gap-1">
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    Create a new insight
                                </Heading>
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    Build a new insight and add it to this dashboard
                                </Text>
                            </div>
                            <div className="ml-auto flex flex-wrap items-center gap-2">
                                {quickCreate.map(({ type, icon: Icon, label, url, dataAttr, tooltip }) => (
                                    <Button
                                        key={type}
                                        variant="outline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={url} />}
                                        tooltip={tooltip}
                                        data-attr={dataAttr}
                                        onClick={() => onCreateClicked(type)}
                                    >
                                        {Icon && <Icon />}
                                        {label}
                                    </Button>
                                ))}
                                <DropdownMenu>
                                    <DropdownMenuTrigger render={<Button variant="outline" />}>
                                        More
                                        <IconChevronDown />
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                        {moreCreate.map(({ type, icon: Icon, label, url, dataAttr }) => (
                                            <DropdownMenuItem
                                                key={type}
                                                data-attr={dataAttr}
                                                onClick={() => {
                                                    onCreateClicked(type)
                                                    router.actions.push(url)
                                                }}
                                            >
                                                {Icon && <Icon />}
                                                {label}
                                            </DropdownMenuItem>
                                        ))}
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </div>
                        </div>
                        <AddSavedInsightsToDashboard />
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
