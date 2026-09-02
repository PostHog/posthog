import { PasteRule, PasteRuleMatch } from '@tiptap/core'
import { Link, LinkOptions } from '@tiptap/extension-link'

/**
 * TLDs we're willing to autolink when the text carries no scheme. Deliberately narrow: plenty of
 * gTLDs double as property names (`.properties`, `.email`, `.name`, `.id`), so linkify reads a path
 * like `person.properties.plan` as a domain and hyperlinks it. Anything missing from this list still
 * becomes a link with an explicit `https://`, a `www.` prefix, or the link button.
 *
 * Country codes that read as property names are left out on purpose: id, is, as, to, on, by, do, re, am, so.
 */
const AUTOLINK_TLDS = new Set(
    `ai app biz blog cc cloud co com dev edu fm gov info int io mil net news online org shop site store tech tv wiki xyz
     ae ar at au be br ca ch cl cn cz de dk eg es eu fi fr gg gr hk hu ie il in it jp ke kr ly me mx my ng nl no nz ph
     pl pt ro ru sa se sg sh th tr tw ua uk us vn za`.split(/\s+/)
)

const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i
/** A dot followed by more identifier characters — i.e. the match ended mid-word. */
const CONTINUES_WORD_RE = /^\.[\w$]/
const IDENTIFIER_CHAR_RE = /[\w$]/

/** Whether an autolink candidate looks like a URL rather than a dotted property path. */
function shouldAutoLink(candidate: string): boolean {
    // An explicit scheme means the author meant a URL. TipTap runs its own `isAllowedUri` protocol
    // check before this, so `javascript:` and friends never get here.
    if (SCHEME_RE.test(candidate)) {
        return true
    }
    // Strip userinfo (emails) and everything after the host, the way TipTap's own default does
    const hostname = candidate
        .split('@')
        .slice(-1)[0]
        .split(/[/?#:]/)[0]
        .toLowerCase()
    if (hostname.startsWith('www.')) {
        return true
    }
    return AUTOLINK_TLDS.has(hostname.split('.').slice(-1)[0])
}

/**
 * linkify stops at the last segment that looks like a TLD, so `person.properties.plan` matches only
 * `person.properties`. A pasted URL fills its whole word, so ignore matches that are butted up
 * against more identifier characters.
 */
function coversWholeWord(text: string, match: PasteRuleMatch): boolean {
    const charBefore = text[match.index - 1]
    if (charBefore && (IDENTIFIER_CHAR_RE.test(charBefore) || charBefore === '.')) {
        return false
    }
    return !CONTINUES_WORD_RE.test(text.slice(match.index + match.text.length))
}

/**
 * `@tiptap/extension-link`, minus the autolinking of code that only looks like a domain. Use this
 * everywhere instead of importing `Link` directly, so every editor behaves the same.
 */
export const LinkExtension = Link.extend({
    addOptions(): LinkOptions {
        return { ...this.parent?.(), shouldAutoLink } as LinkOptions
    },

    addPasteRules() {
        return (this.parent?.() ?? []).map((rule) => {
            const { find } = rule
            if (typeof find !== 'function') {
                return rule
            }
            return new PasteRule({
                handler: rule.handler,
                find: (text, event) => find(text, event)?.filter((match) => coversWholeWord(text, match)),
            })
        })
    },
})
