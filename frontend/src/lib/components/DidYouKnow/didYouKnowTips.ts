export const DID_YOU_KNOW_TIPS = {
    SQL_EDITOR_SHORTCUT: 'sql-editor-shortcut',
} as const

export type DidYouKnowTipKey = (typeof DID_YOU_KNOW_TIPS)[keyof typeof DID_YOU_KNOW_TIPS]

const DID_YOU_KNOW_FLAG_PREFIX = 'did-you-know-'

export function didYouKnowFlagKey(tipKey: DidYouKnowTipKey): string {
    return `${DID_YOU_KNOW_FLAG_PREFIX}${tipKey}`
}
