// @ts-nocheck
// Test fixture for the country-flag-polyfill-via-wrapper rule.

// ruleid: country-flag-polyfill-via-wrapper
import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'

// ruleid: country-flag-polyfill-via-wrapper
import polyfill from 'country-flag-emoji-polyfill'

// ruleid: country-flag-polyfill-via-wrapper
import * as flags from 'country-flag-emoji-polyfill'

// ruleid: country-flag-polyfill-via-wrapper
import 'country-flag-emoji-polyfill'

// A direct import stays a finding even when the call passes a URL, because the next call
// site added next to it is the one that forgets.
// ruleid: country-flag-polyfill-via-wrapper
const dynamic = import('country-flag-emoji-polyfill')

// ruleid: country-flag-polyfill-via-wrapper
const required = require('country-flag-emoji-polyfill')

// ok: country-flag-polyfill-via-wrapper
import { polyfillCountryFlags } from 'lib/countryFlagEmojiPolyfill'

// ok: country-flag-polyfill-via-wrapper
const wrapped = import('lib/countryFlagEmojiPolyfill')

// A package whose name merely contains the same words is not this one.
// ok: country-flag-polyfill-via-wrapper
import { other } from 'country-flag-emoji-polyfill-helpers'
