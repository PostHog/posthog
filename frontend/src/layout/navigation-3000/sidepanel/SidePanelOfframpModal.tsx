import { Tabs } from '@base-ui/react/tabs'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconSidePanel } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { StopSignHog } from 'lib/components/hedgehogs'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'
import { cn } from 'lib/utils/css-classes'

import sidepanelNewImage from './images/sidepanel-new.gif'
import sidepanelOldImage from './images/sidepanel-old.gif'
import { sidePanelOfframpLogic } from './sidePanelOfframpLogic'

interface OfframpStep {
    id: string
    title: string
    description: React.ReactNode
    action?: {
        label?: string
        onClick?: () => void
        type?: 'primary' | 'secondary' | 'tertiary'
    }
    image?: string
    icon?: React.ReactNode
}

export function SidePanelOfframpModal(): JSX.Element {
    const { shouldShowOfframpModal } = useValues(sidePanelOfframpLogic)
    const { dismissOfframpModal } = useActions(sidePanelOfframpLogic)
    const contentRef = useRef<HTMLDivElement>(null)
    const steps: OfframpStep[] = [
        {
            id: 'oh-boy',
            title: "We've made some changes!",
            description: "Some text you probably won't read, and if you don't that's totally fine!",
            action: {
                label: "Naw, I'll figure it out thanks",
                onClick: () => dismissOfframpModal(),
                type: 'tertiary',
            },
            icon: (
                <div aria-hidden="true" className="size-8 opacity-0 p-1">
                    <IconBlank />
                </div>
            ),
        },
        {
            id: 'side-panel',
            title: 'Goodbye side panel...',
            description:
                "That large thing on the right side of the screen? Yeah, we've removed it. The features aren't gone, just moved.",
            image: sidepanelOldImage,
            icon: (
                <div aria-hidden="true" className="size-8 opacity-0 p-1">
                    <IconBlank />
                </div>
            ),
        },
        {
            id: 'side-panel-new',
            title: 'Hello context panel!',
            description: (
                <>
                    Contextual info & actions, <strong>PostHog AI</strong>, <strong>Support</strong>,{' '}
                    <strong>Notebooks</strong>, <strong>Discussions</strong> & <strong>Access control</strong> are now
                    neatly tucked away.
                </>
            ),
            image: sidepanelNewImage,
            icon: (
                <div className="size-8 flex items-center justify-center text-primary border border-primary rounded-sm p-1">
                    <IconSidePanel />
                </div>
            ),
        },
    ]

    const [activeTab, setActiveTab] = useState(steps[0].id)
    const activeIndex = steps.findIndex((s) => s.id === activeTab)
    const isLastStep = activeIndex === steps.length - 1
    const isFirstStep = activeIndex === 0

    useEffect(() => {
        contentRef.current?.focus()
    }, [activeTab])

    return (
        <DialogPrimitive
            open={shouldShowOfframpModal}
            onOpenChange={(open, event) => {
                if (event?.reason === 'escape-key') {
                    event.cancel()
                    return
                }
                if (event?.reason === 'outside-press') {
                    event.cancel()
                    return
                }
                if (!open) {
                    dismissOfframpModal()
                }
            }}
            className="group bg-surface-popover w-[300px] md:w-[640px] max-h-[none] has-[:focus-visible]:outline-2 outline-transparent has-[:focus-visible]:outline-accent outline-inset"
        >
            <DialogPrimitiveTitle>Hey there, we've changed some things!</DialogPrimitiveTitle>
            <Tabs.Root value={activeTab} onValueChange={setActiveTab}>
                <Tabs.List className="sr-only">
                    {steps.map((step) => (
                        <Tabs.Tab key={step.id} value={step.id}>
                            {step.title}
                        </Tabs.Tab>
                    ))}
                </Tabs.List>

                {steps.map((step) => (
                    <Tabs.Panel
                        ref={step.id === activeTab ? contentRef : undefined}
                        key={step.id}
                        value={step.id}
                        className="focus:outline-none"
                        onKeyDown={(e) => {
                            if (e.key === 'ArrowRight' && !isLastStep) {
                                setActiveTab(steps[activeIndex + 1].id)
                            } else if (e.key === 'ArrowLeft' && !isFirstStep) {
                                setActiveTab(steps[activeIndex - 1].id)
                            }
                        }}
                    >
                        <div className="flex flex-col @md:flex-row">
                            <div
                                className={cn(
                                    'overflow-hidden bg-fill-tertiary @md:rounded-bl-lg shrink-0 h-[300px] w-full @md:w-1/2'
                                )}
                            >
                                {!isFirstStep && step.image && (
                                    <img src={step.image} alt={step.title} className="w-full h-full" />
                                )}
                                {isFirstStep && (
                                    <div className="mx-auto w-32 h-full flex items-center justify-center">
                                        <StopSignHog />
                                    </div>
                                )}
                            </div>
                            <div className="flex flex-col gap-3 p-6 flex-1 @md:pt-14 text-left items-start">
                                {step.icon && step.icon}
                                <h3 className="text-lg font-semibold m-0">{step.title}</h3>
                                <p className="text-sm text-secondary m-0">{step.description}</p>
                                {isFirstStep && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        className={cn('self-left mt-2', step.image && 'self-start')}
                                        onClick={dismissOfframpModal}
                                    >
                                        Naw, I'll figure it out thanks
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </Tabs.Panel>
                ))}

                <div className="grid grid-cols-2 @xl:grid-cols-[140px_auto_140px] items-center justify-between px-4 py-3 border-t border-primary">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={() => (isFirstStep ? undefined : setActiveTab(steps[activeIndex - 1].id))}
                        className={cn(
                            'hidden @xl:block justify-self-start',
                            isFirstStep && 'cursor-default opacity-0 pointer-events-none'
                        )}
                        tabIndex={isFirstStep ? -1 : 0}
                    >
                        Back
                    </LemonButton>
                    <ButtonPrimitive
                        onClick={() => (isFirstStep ? undefined : setActiveTab(steps[activeIndex - 1].id))}
                        className={cn(
                            '@xl:hidden justify-self-start',
                            isFirstStep && 'cursor-default opacity-0 pointer-events-none'
                        )}
                        tabIndex={isFirstStep ? -1 : 0}
                        size="lg"
                    >
                        <IconArrowLeft />
                    </ButtonPrimitive>
                    <div className="gap-1.5 hidden @xl:flex">
                        {steps.map((step, i) => (
                            <button
                                key={step.id}
                                type="button"
                                className={`w-2 h-2 rounded-full transition-colors ${
                                    i === activeIndex ? 'bg-accent' : 'bg-fill-tertiary'
                                }`}
                                onClick={() => setActiveTab(step.id)}
                            />
                        ))}
                    </div>
                    {isLastStep ? (
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={dismissOfframpModal}
                            className="justify-self-end"
                        >
                            Don't show again
                        </LemonButton>
                    ) : (
                        <>
                            <LemonButton
                                type="primary"
                                size="small"
                                className="hidden @xl:block justify-self-end"
                                onClick={() => setActiveTab(steps[activeIndex + 1].id)}
                            >
                                Next
                            </LemonButton>
                            <ButtonPrimitive
                                className="@xl:hidden justify-self-end"
                                variant="outline"
                                size="lg"
                                onClick={() => setActiveTab(steps[activeIndex + 1].id)}
                            >
                                <IconArrowRight />
                            </ButtonPrimitive>
                        </>
                    )}
                </div>
            </Tabs.Root>
        </DialogPrimitive>
    )
}
