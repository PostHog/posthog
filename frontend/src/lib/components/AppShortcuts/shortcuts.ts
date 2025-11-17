import { AppShortcutDeuxType } from './appShortcutDeuxLogic'

type ShortcutConstant = Omit<AppShortcutDeuxType, 'ref'>

type ShortcutBase = Record<string, ShortcutConstant>
export type ShortcutConstantType = {
    global: ShortcutBase
} & {
    Dashboards?: ShortcutBase
}

export const baseModifier = ['command', 'option']

export const keyBinds: Record<string, string[]> = {
    newTab: [...baseModifier, 't'],
    closeActiveTab: [...baseModifier, 'w'],
    new: [...baseModifier, 'n'],
    edit: [...baseModifier, 'e'],
}
