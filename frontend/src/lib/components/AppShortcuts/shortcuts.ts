export const baseModifier = ['command', 'option']

export const keyBinds: Record<string, string[]> = {
    newTab: [...baseModifier, 't'],
    closeActiveTab: [...baseModifier, 'w'],
    toggleShortcutMenu: [...baseModifier, 'k'],
    toggleShortcutMenuFallback: ['command', 'shift', 'k'],
    search: ['command', 'k'],
    new: [...baseModifier, 'n'],
    edit: [...baseModifier, 'e'],
    save: [...baseModifier, 's'],
    dashboardAddTextTile: [...baseModifier, 'a'],
}
