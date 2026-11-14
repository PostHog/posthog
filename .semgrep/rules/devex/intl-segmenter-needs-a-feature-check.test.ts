// @ts-nocheck
// Test fixture for the intl-segmenter-needs-a-feature-check rule.

// ruleid: intl-segmenter-needs-a-feature-check
const graphemes = new Intl.Segmenter(undefined, { granularity: 'grapheme' })

// ruleid: intl-segmenter-needs-a-feature-check
const words = new Intl.Segmenter('und', { granularity: 'word' })

function lazy() {
    if (segmenter === undefined) {
        // ok: intl-segmenter-needs-a-feature-check
        segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter('und', { granularity: 'grapheme' }) : null
    }
    return segmenter
}

function lazyBlock() {
    if (typeof Intl.Segmenter === 'function') {
        // ok: intl-segmenter-needs-a-feature-check
        return new Intl.Segmenter('und', { granularity: 'grapheme' })
    }
    return null
}
