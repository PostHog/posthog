// Helpers for Kea issue with double importing
import { JSONContent as TTJSONContent, Editor as TTEditor } from '@tiptap/core'

// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface JSONContent extends TTJSONContent {}
// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface Editor extends TTEditor {}
