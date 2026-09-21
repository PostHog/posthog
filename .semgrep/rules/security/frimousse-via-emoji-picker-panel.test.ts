// @ts-nocheck
// Test fixture for the frimousse-via-emoji-picker-panel rule.

// ruleid: frimousse-via-emoji-picker-panel
import { EmojiPicker } from 'frimousse'

// ruleid: frimousse-via-emoji-picker-panel
import frimousse from 'frimousse'

// ruleid: frimousse-via-emoji-picker-panel
import * as Frimousse from 'frimousse'

// ruleid: frimousse-via-emoji-picker-panel
import 'frimousse'

// ruleid: frimousse-via-emoji-picker-panel
const dynamic = import('frimousse')

// ruleid: frimousse-via-emoji-picker-panel
const required = require('frimousse')

// A module that re-exports the package hands the CDN default to every file that imports it.
// ruleid: frimousse-via-emoji-picker-panel
export { EmojiPicker as ReexportedPicker } from 'frimousse'

// ruleid: frimousse-via-emoji-picker-panel
export * from 'frimousse'

// ruleid: frimousse-via-emoji-picker-panel
export * as FrimousseReexport from 'frimousse'

// ok: frimousse-via-emoji-picker-panel
import { EmojiPickerPanel } from 'lib/components/EmojiPicker/EmojiPickerPanel'

// ok: frimousse-via-emoji-picker-panel
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'

// A package whose name merely starts with the same word is not this one.
// ok: frimousse-via-emoji-picker-panel
import { other } from 'frimousse-helpers'

// ok: frimousse-via-emoji-picker-panel
export * from 'frimousse-helpers'
