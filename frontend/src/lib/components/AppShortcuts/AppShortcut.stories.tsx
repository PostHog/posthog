import type { Meta } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextInputPrimitive } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
import { Scene } from 'scenes/sceneTypes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { AppShortcut } from './AppShortcut'
import { AppShortcutMenu } from './AppShortcutMenu'
import { appShortcutLogic } from './appShortcutLogic'

const meta = {
    title: 'UI/AppShortcut',
    component: AppShortcut as any,
    tags: ['autodocs'],
} satisfies Meta<typeof AppShortcut>

export default meta

export function Default(): JSX.Element {
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { appShortcutMenuOpen } = useValues(appShortcutLogic)
    const lemonInputRef = useRef<HTMLInputElement>(null)
    const sliderRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (lemonInputRef.current) {
            lemonInputRef.current.focus()
        }
    }, [lemonInputRef])

    useEffect(() => {
        if (sliderRef.current) {
            sliderRef.current.focus()
        }
    }, [sliderRef])

    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <div className="flex flex-col gap-2 [&_p]:mb-0">
                <p>AppShortcuts are an easy way to add keyboard shortcuts to your app:</p>
                <ul className="list-disc pl-4">
                    <li>
                        Wrap an input or button in an AppShortcut to add a keyboard shortcut to it. Then you get access
                        to it in the AppShortcutMenu.
                    </li>
                    <li>
                        KeyboardShortcut like this: <KeyboardShortcut command /> somewhere in the element is optional,
                        but it's a good idea to include it to make it easier to understand what the keyboard shortcut is
                        for. Otherwise make sure theres a tooltip.
                    </li>
                    <li>
                        NOTE: Passing a scene key as the scope prop will only register/show the shortcut when the scene
                        is active.
                    </li>
                </ul>
            </div>

            <AppShortcut
                name="ShownOnlyWhenSceneIsActive"
                keybind={['command', 'option', 'm']}
                intent="DASHBOARD SCENE ONLY: press with cmd + option + m"
                interaction="click"
                asChild
                scope={Scene.Dashboard}
            >
                <ButtonPrimitive
                    variant="outline"
                    onClick={() => {
                        alert('clicked or pressed cmd + option + m')
                    }}
                >
                    Show in menu only when Dashboard scene is active <KeyboardShortcut command option m />
                </ButtonPrimitive>
            </AppShortcut>

            <AppShortcut
                name="SomeName"
                keybind={['command', 'option', 'x']}
                intent="press with cmd + option + x"
                interaction="click"
                asChild
            >
                <ButtonPrimitive
                    variant="outline"
                    onClick={() => {
                        alert('clicked or pressed cmd + option + x')
                    }}
                >
                    Fire my onClick <KeyboardShortcut command option x className="ml-auto" />
                </ButtonPrimitive>
            </AppShortcut>

            <AppShortcut
                name="SomeOtherName"
                keybind={['command', 'option', 'z']}
                intent="press with cmd + option + z"
                interaction="click"
                asChild
            >
                <LemonButton
                    type="primary"
                    onClick={() => {
                        alert('clicked or pressed cmd + option + z')
                    }}
                >
                    Fire my onClick <KeyboardShortcut command option z className="ml-auto" />
                </LemonButton>
            </AppShortcut>

            <AppShortcut
                name="SomeTextInputName"
                keybind={['command', 'option', 'e']}
                intent="focus input with cmd + option + e"
                interaction="focus"
                asChild
            >
                <TextInputPrimitive placeholder="press cmd + option + e to focus" />
            </AppShortcut>

            <AppShortcut
                name="SomeLemonInputName"
                keybind={['command', 'option', 'r']}
                intent="focus LemonInput with cmd + option + r"
                interaction="focus"
                // Here we use the targetRef prop to pass in the ref to the LemonInput component, as it doesn't forward the ref to the input element
                targetRef={lemonInputRef}
            >
                <LemonInput placeholder="press cmd + option + r to focus" inputRef={lemonInputRef} />
            </AppShortcut>

            <div className="flex gap-2">
                <AppShortcut
                    name="ShortcutMenuTrigger"
                    keybind={['command', 'shift', 'k']}
                    intent="toggle shortcut menu"
                    interaction="click"
                    asChild
                >
                    <LemonButton
                        type="secondary"
                        onClick={() => setAppShortcutMenuOpen(!appShortcutMenuOpen)}
                        tooltip="If child has a tooltip prop, we inject the keyboard shortcut at the end"
                    >
                        Open Shortcut Menu
                        <KeyboardShortcut command shift k className="ml-1" />
                    </LemonButton>
                </AppShortcut>
            </div>

            <AppShortcutMenu />
        </div>
    )
}

export function AppShortcutMenuExample(): JSX.Element {
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { appShortcutMenuOpen } = useValues(appShortcutLogic)

    useEffect(() => {
        setAppShortcutMenuOpen(true)
    }, [])

    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <AppShortcut
                name="SomeTextInputName"
                keybind={['command', 'option', 'e']}
                intent="focus input with cmd + option + e"
                interaction="focus"
                asChild
            >
                <TextInputPrimitive placeholder="press cmd + option + e to focus" />
            </AppShortcut>

            <div className="flex gap-2">
                <AppShortcut
                    name="ShortcutMenuTrigger"
                    keybind={['command', 'shift', 'k']}
                    intent="toggle shortcut menu"
                    interaction="click"
                    asChild
                >
                    <LemonButton
                        type="secondary"
                        onClick={() => setAppShortcutMenuOpen(!appShortcutMenuOpen)}
                        tooltip="If child has a tooltip prop, we inject the keyboard shortcut at the end"
                    >
                        Open Shortcut Menu
                        <KeyboardShortcut command shift k className="ml-1" />
                    </LemonButton>
                </AppShortcut>
            </div>

            <AppShortcutMenu />
        </div>
    )
}
export function AppShortcutMenuEmptyExample(): JSX.Element {
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)

    useEffect(() => {
        setAppShortcutMenuOpen(true)
    }, [])

    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <AppShortcutMenu />
        </div>
    )
}
