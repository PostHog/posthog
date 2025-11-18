export const baseModifier = ['command', 'option']

export const keyBinds: Record<string, string[]> = {
    newTab: [...baseModifier, 't'],
    closeActiveTab: [...baseModifier, 'w'],
    new: [...baseModifier, 'n'],
    edit: [...baseModifier, 'e'],
    dashboardAddTextTile: [...baseModifier, 'a'],
}
