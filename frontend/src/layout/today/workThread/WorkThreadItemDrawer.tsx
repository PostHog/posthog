import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconArrowRight } from '@posthog/icons'
import {
    Button,
    Drawer,
    DrawerBody,
    DrawerClose,
    DrawerContent,
    DrawerDescription,
    DrawerFooter,
    DrawerHeader,
    DrawerTitle,
    useDirection,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { WorkStepApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { captureWorkItemOpened } from './workThreadEvents'
import { WorkThreadFacts } from './WorkThreadFacts'
import { workThreadLogic } from './workThreadLogic'
import { workStepByKey } from './workThreadState'

interface WorkThreadItemDrawerProps {
    thread: WorkThreadApi
    renderEvidence?: (step: WorkStepApi) => JSX.Element | null
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}

export function WorkThreadItemDrawer({ thread, renderEvidence }: WorkThreadItemDrawerProps): JSX.Element {
    const logic = workThreadLogic({ threadKey: thread.key })
    const { viewedStepKey } = useValues(logic)
    const { closeItem } = useActions(logic)
    const direction = useDirection()

    const viewedStep = viewedStepKey ? workStepByKey(thread, viewedStepKey) : null
    // Keeps the content while the drawer slides out, after the logic has already cleared the step.
    const shownStepRef = useRef<WorkStepApi | null>(null)
    if (viewedStep) {
        shownStepRef.current = viewedStep
    }
    const step = viewedStep ?? shownStepRef.current
    const item = step?.item ?? null
    const card = step ? (renderEvidence?.(step) ?? null) : null

    return (
        <Drawer
            open={!!viewedStep?.item}
            onOpenChange={(open) => !open && closeItem()}
            swipeDirection={direction === 'rtl' ? 'left' : 'right'}
        >
            <DrawerContent data-attr="work-thread-item-drawer">
                {step && item && (
                    <>
                        <DrawerHeader>
                            <DrawerTitle className="break-words">{item.name}</DrawerTitle>
                            <DrawerDescription>{`${capitalize(item.kind_label)} · ${item.product}`}</DrawerDescription>
                        </DrawerHeader>
                        <DrawerBody>
                            <div className="flex flex-col gap-4">
                                {card}
                                {step.facts.length > 0 && <WorkThreadFacts facts={step.facts} />}
                            </div>
                        </DrawerBody>
                        <DrawerFooter>
                            <DrawerClose
                                render={<Button variant="outline" data-attr="work-thread-item-drawer-close" />}
                            >
                                Close
                            </DrawerClose>
                            <Button
                                variant="primary"
                                nativeButton={false}
                                render={<LinkPrimitive to={item.href} />}
                                onClick={() => {
                                    captureWorkItemOpened(thread, item)
                                    closeItem()
                                }}
                                data-attr="work-thread-item-drawer-open"
                            >
                                <span>{`Open in ${item.product}`}</span>
                                <IconArrowRight />
                            </Button>
                        </DrawerFooter>
                    </>
                )}
            </DrawerContent>
        </Drawer>
    )
}
