import { DefaultTreeAdapterMap, parse } from 'parse5'

// The href of each anchor in document order, read by a spec-compliant HTML parser rather than a pattern over the
// markup, so a test sees the link a browser follows.
export const anchorHrefs = (html: string): (string | undefined)[] => {
    const hrefs: (string | undefined)[] = []
    const nodes: DefaultTreeAdapterMap['node'][] = [parse(html)]
    for (let node = nodes.shift(); node; node = nodes.shift()) {
        if ('tagName' in node && node.tagName === 'a') {
            hrefs.push(node.attrs.find((attribute) => attribute.name === 'href')?.value)
        }
        if ('childNodes' in node) {
            nodes.unshift(...node.childNodes)
        }
    }
    return hrefs
}
