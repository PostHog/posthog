import { Tabs } from '@base-ui/react/tabs'
import { useActions, useValues } from 'kea'

import { IconHome, IconSparkles } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { NavTabChat } from './NavTabChat'
import { NavTabInbox } from './NavTabInbox'
import { NavExperimentTab, panelLayoutLogic } from './panelLayoutLogic'

const TAB_CONFIG: { id: NavExperimentTab; label: string; icon: JSX.Element }[] = [
    { id: 'home', label: 'Home', icon: <IconHome /> },
    { id: 'chat', label: 'Chat', icon: <IconSparkles className="text-ai" /> },
]

interface TabbedNavBarProps {
    children: React.ReactNode
}

export function TabbedNavBar({ children }: TabbedNavBarProps): JSX.Element {
    const { navExperimentActiveTab } = useValues(panelLayoutLogic)
    const { setNavExperimentTab } = useActions(panelLayoutLogic)

    return (
        <Tabs.Root
            className="flex flex-col flex-1 overflow-hidden"
            value={navExperimentActiveTab}
            onValueChange={(value) => setNavExperimentTab(value as NavExperimentTab)}
        >
            <Tabs.List className="relative flex items-center gap-1 px-1 shrink-0 z-0 mb-1">
                {TAB_CONFIG.map((tab) => (
                    <Tabs.Tab
                        key={tab.id}
                        value={tab.id}
                        render={(props) => (
                            <ButtonPrimitive
                                {...props}
                                className="w-auto hover:bg-transparent group justify-normal"
                                data-attr={`nav-tab-${tab.id}`}
                            >
                                <span
                                    className={cn(
                                        'flex size-4',
                                        navExperimentActiveTab === tab.id
                                            ? 'text-primary'
                                            : 'text-tertiary group-hover:text-primary'
                                    )}
                                >
                                    {tab.icon}
                                </span>
                                <span
                                    className={cn(
                                        'text-xs',
                                        navExperimentActiveTab === tab.id
                                            ? 'text-primary'
                                            : 'text-tertiary group-hover:text-primary'
                                    )}
                                >
                                    {tab.label}
                                </span>
                            </ButtonPrimitive>
                        )}
                    />
                ))}

                <Tabs.Indicator className="transform-gpu absolute top-1/2 left-0 z-[-1] h-full w-[var(--active-tab-width)] translate-x-[var(--active-tab-left)] -translate-y-1/2 rounded bg-[var(--color-bg-fill-button-tertiary-active)] transition-all duration-200 ease-in-out" />
            </Tabs.List>

            <div className="h-px bg-border-primary w-full" />

            <div className="flex-1 overflow-hidden relative">
                <Tabs.Panel
                    value="home"
                    className={cn(
                        'absolute inset-0 flex flex-col',
                        'transition-[opacity,transform] duration-200 ease-in-out',
                        'data-[hidden]:opacity-0 data-[hidden]:-translate-x-2 data-[hidden]:pointer-events-none'
                    )}
                    keepMounted
                >
                    {children}
                </Tabs.Panel>
                <Tabs.Panel
                    value="chat"
                    className={cn(
                        'absolute inset-0 flex flex-col',
                        'transition-[opacity,transform] duration-200 ease-in-out',
                        'data-[hidden]:opacity-0 data-[hidden]:translate-x-2 data-[hidden]:pointer-events-none'
                    )}
                    keepMounted
                >
                    <NavTabChat />
                </Tabs.Panel>
                <Tabs.Panel
                    value="inbox"
                    className={cn(
                        'absolute inset-0 flex flex-col',
                        'transition-[opacity,transform] duration-200 ease-in-out',
                        'data-[hidden]:opacity-0 data-[hidden]:translate-x-2 data-[hidden]:pointer-events-none'
                    )}
                    keepMounted
                >
                    <NavTabInbox />
                </Tabs.Panel>
            </div>
        </Tabs.Root>
    )
}
