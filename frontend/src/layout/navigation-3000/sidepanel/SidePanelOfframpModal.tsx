import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { healthMenuLogic } from 'lib/components/HealthMenu/healthMenuLogic'
import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DialogPrimitive, DialogPrimitiveTitle } from 'lib/ui/DialogPrimitive/DialogPrimitive'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'

import { SidePanelTab } from '~/types'

import accountMenuImage from './images/sidepanel-account.gif'
import healthMenuImage from './images/sidepanel-health.gif'
import helpMenuImage from './images/sidepanel-help.gif'
import sidepanelNewImage from './images/sidepanel-new.gif'
import sidepanelOldImage from './images/sidepanel-old.gif'
import { sidePanelOfframpLogic } from './sidePanelOfframpLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

interface OfframpStep {
    id: string
    title: string
    description: React.ReactNode
    action?: {
        label: string
        onClick: () => void
        type?: 'primary' | 'secondary' | 'tertiary'
        keybind?: string[][]
    }
    image?: string
}

export function SidePanelOfframpModal(): JSX.Element {
    const { shouldShowOfframpModal } = useValues(sidePanelOfframpLogic)
    const { dismissOfframpModal } = useActions(sidePanelOfframpLogic)
    const { toggleAccountMenu } = useActions(newAccountMenuLogic)
    const { toggleHelpMenu } = useActions(helpMenuLogic)
    const { toggleHealthMenu } = useActions(healthMenuLogic)
    const { openSidePanel, setSidePanelOpen } = useActions(sidePanelStateLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)

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
        },
        {
            id: 'side-panel',
            title: 'Side panel has moved',
            description: "But don't worry, it still exists!",
            image: sidepanelOldImage,
        },
        {
            id: 'side-panel-new',
            title: 'Dot dot dot!',
            description: (
                <>
                    <strong>PostHog AI</strong>, <strong>Support</strong>, <strong>Discussions</strong> &{' '}
                    <strong>Access control</strong> are now behind the{' '}
                    <RenderKeybind className="" keybind={[['...']]} /> button on most pages.
                </>
            ),
            action: {
                label: 'Toggle',
                onClick: () => (sidePanelOpen ? setSidePanelOpen(false) : openSidePanel(SidePanelTab.Max)),
                keybind: [[']']],
            },
            image: sidepanelNewImage,
        },
        {
            id: 'account-menu',
            title: 'Account menu',
            description: 'Your account settings, project switching, and sign out are now in the account menu.',
            action: {
                label: 'Toggle',
                onClick: () => toggleAccountMenu(),
                keybind: [keyBinds.newAccountMenu],
            },
            image: accountMenuImage,
        },
        {
            id: 'help-menu',
            title: 'Help menu',
            description: 'Support, docs, and other resources are now in the help menu.',
            action: {
                label: 'Toggle',
                onClick: () => toggleHelpMenu(),
                keybind: [keyBinds.helpMenu],
            },
            image: helpMenuImage,
        },
        {
            id: 'health-menu',
            title: 'Health menu',
            description: 'System status and health information are now in the health menu.',
            action: {
                label: 'Toggle',
                onClick: () => toggleHealthMenu(),
                keybind: [keyBinds.healthMenu],
            },
            image: healthMenuImage,
        },
    ]

    const [activeTab, setActiveTab] = useState(steps[0].id)
    const activeIndex = steps.findIndex((s) => s.id === activeTab)
    const isLastStep = activeIndex === steps.length - 1
    const isFirstStep = activeIndex === 0

    return (
        <DialogPrimitive
            open={shouldShowOfframpModal}
            onOpenChange={(open, event) => {
                if (event.reason === 'escape-key') {
                    event.cancel()
                    return
                }
                if (event.reason === 'outside-press') {
                    event.cancel()
                    return
                }
                if (!open) {
                    dismissOfframpModal()
                }
            }}
            className="bg-surface-popover w-[300px] md:w-[640px] max-h-[none]"
        >
            <DialogPrimitiveTitle>Hey there, we've changed some things!</DialogPrimitiveTitle>
            <TabsPrimitive value={activeTab} onValueChange={setActiveTab}>
                <TabsPrimitiveList className="sr-only">
                    {steps.map((step) => (
                        <TabsPrimitiveTrigger key={step.id} value={step.id}>
                            {step.title}
                        </TabsPrimitiveTrigger>
                    ))}
                </TabsPrimitiveList>

                {steps.map((step) => (
                    <TabsPrimitiveContent key={step.id} value={step.id} className="focus:outline-none">
                        <div className="flex flex-col @md:flex-row">
                            <div
                                className={cn(
                                    'overflow-hidden bg-fill-tertiary @md:rounded-bl-lg shrink-0 h-[300px]',
                                    step.image && 'w-full @md:w-1/2'
                                )}
                            >
                                {step.image && <img src={step.image} alt={step.title} className="w-full h-full" />}
                            </div>
                            <div
                                className={cn(
                                    'flex flex-col gap-3 p-6 flex-1 pt-4 @md:pt-14 text-center justify-center items-center',
                                    step.image && 'text-left items-start'
                                )}
                            >
                                <h3 className="text-lg font-semibold m-0">{step.title}</h3>
                                <p className="text-sm text-secondary m-0">{step.description}</p>
                                {step.action && (
                                    <LemonButton
                                        type={step.action.type || 'secondary'}
                                        size="small"
                                        className={cn('self-center @md:self-center mt-2', step.image && 'self-start')}
                                        onClick={step.action.onClick}
                                    >
                                        {step.action.label}
                                        {step.action.keybind && (
                                            <RenderKeybind
                                                className="[&>kbd]:pb-[3px] ml-1"
                                                keybind={step.action.keybind}
                                            />
                                        )}
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </TabsPrimitiveContent>
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
            </TabsPrimitive>
        </DialogPrimitive>
    )
}
