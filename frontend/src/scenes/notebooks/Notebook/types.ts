// Helpers for Kea issue with double importing
import { JSONContent as TTJSONContent } from '@tiptap/core'
import { Node as PMNode } from '@tiptap/pm/model'

export interface TipTapNode extends PMNode {}
export interface JSONContent extends TTJSONContent {}

export {
    ChainedCommands as EditorCommands,
    Range as EditorRange,
    FocusPosition as EditorFocusPosition,
} from '@tiptap/core'
