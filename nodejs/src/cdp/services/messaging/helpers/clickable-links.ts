import { DefaultTreeAdapterMap, parse } from 'parse5'

type ParentNode = DefaultTreeAdapterMap['parentNode']

export const UNSUBSCRIBE_PLACEHOLDER = /\{\{\s*unsubscribe_url\s*\}\}/g

export const clickableHrefs = (body: string): string[] => {
    const hrefs: string[] = []
    const parents: ParentNode[] = [parse(body)]
    for (let parent = parents.pop(); parent; parent = parents.pop()) {
        for (const child of parent.childNodes) {
            if (!('tagName' in child)) {
                continue
            }
            const href = child.tagName === 'a' ? child.attrs.find(({ name }) => name === 'href') : undefined
            if (href) {
                hrefs.push(href.value)
            }
            parents.push(child)
        }
    }
    return hrefs
}
