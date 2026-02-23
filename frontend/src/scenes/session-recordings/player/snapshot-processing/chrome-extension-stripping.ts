import { serializedNodeWithId } from '@posthog/rrweb-types'

// we have seen some chrome extensions
// that break playback of session recordings
// let's try to strip them out
export const CHROME_EXTENSION_DENY_LIST: Record<string, string> = {
    'dji-sru': 'snap and read',
    mloajfnmjckfjbeeofcdaecbelnblden: 'snap and read',
    aitopia: 'aitopia',
    becfinhbfclcgokjlobojlnldbfillpf: 'aitopia',
    fnliebffpgomomjeflboommgbdnjadbh: 'sublime pop-up',
    'sublime-root': 'sublime pop-up',
}

interface IsStrippable {
    textContent: string
    attributes: Record<string, string>
    childNodes: serializedNodeWithId[]
}

function safelyCheckCSSAttribute(
    node: serializedNodeWithId,
    attribute: string,
    needles: string[],
    matchedExtensions: Set<string>
): node is IsStrippable & serializedNodeWithId {
    const hasAttributes = 'attributes' in node && attribute in node.attributes && !!node.attributes[attribute]
    if (!hasAttributes) {
        return false
    }
    const attributeValue = node.attributes[attribute]
    if (typeof attributeValue !== 'string') {
        return false
    }

    if (attributeValue.includes('chrome-extension://')) {
        for (const needle of needles) {
            if (attributeValue.includes(needle)) {
                matchedExtensions.add(CHROME_EXTENSION_DENY_LIST[needle] || needle)
                return true
            }
        }
    }
    return false
}

function safelyCheckClassAttribute(
    node: serializedNodeWithId,
    needle: string,
    matchedExtensions: Set<string>
): node is IsStrippable & serializedNodeWithId {
    const hasAttributes = 'attributes' in node && 'class' in node.attributes && !!node.attributes['class']
    if (!hasAttributes) {
        return false
    }
    const attributeValue = node.attributes['class']
    if (typeof attributeValue !== 'string') {
        return false
    }
    if (attributeValue.includes(needle)) {
        matchedExtensions.add(CHROME_EXTENSION_DENY_LIST[needle] || needle)
        return true
    }
    return false
}

function safelyCheckTagName(
    node: serializedNodeWithId,
    needles: string[],
    matchedExtensions: Set<string>
): node is IsStrippable & serializedNodeWithId {
    const hasTagName = 'tagName' in node && typeof node.tagName === 'string'
    if (!hasTagName) {
        return false
    }
    for (const needle of needles) {
        if (node.tagName.includes(needle)) {
            matchedExtensions.add(CHROME_EXTENSION_DENY_LIST[needle] || needle)
            return true
        }
    }
    return false
}

function safelyCheckDivNode(
    node: serializedNodeWithId,
    needles: string[],
    matchedExtensions: Set<string>
): node is IsStrippable & serializedNodeWithId {
    const hasTagName = 'tagName' in node && typeof node.tagName === 'string'
    if (!hasTagName) {
        return false
    }
    if (node.tagName === 'DIV') {
        for (const needle of needles) {
            if (safelyCheckClassAttribute(node, needle, matchedExtensions)) {
                return true
            }
        }
    }
    return false
}

function safelyCheckIDAttribute(
    node: serializedNodeWithId,
    needles: string[],
    matchedExtensions: Set<string>
): node is IsStrippable & serializedNodeWithId {
    const hasID = 'attributes' in node && 'id' in node.attributes && !!node.attributes['id']
    if (!hasID) {
        return false
    }
    const idValue = node.attributes['id']
    if (typeof idValue !== 'string') {
        return false
    }
    for (const needle of needles) {
        if (idValue.includes(needle)) {
            matchedExtensions.add(CHROME_EXTENSION_DENY_LIST[needle] || needle)
            return true
        }
    }
    return false
}

export function stripChromeExtensionDataFromNode(
    node: serializedNodeWithId,
    needles: string[],
    matchedExtensions: Set<string>
): boolean {
    let stripped = false

    if (safelyCheckCSSAttribute(node, 'textContent', needles, matchedExtensions)) {
        node.textContent = ''
        stripped = true
    }
    if (safelyCheckCSSAttribute(node, '_cssText', needles, matchedExtensions)) {
        node.attributes._cssText = ''
        stripped = true
    }
    if (safelyCheckIDAttribute(node, needles, matchedExtensions)) {
        node.childNodes = []
        stripped = true
    }
    for (const needle of needles) {
        if (safelyCheckClassAttribute(node, needle, matchedExtensions)) {
            node.attributes['class'] = node.attributes['class'].replace(needle, '')
            stripped = true
        }
    }
    if (safelyCheckDivNode(node, needles, matchedExtensions)) {
        node.childNodes = []
        stripped = true
    }
    if (safelyCheckTagName(node, needles, matchedExtensions)) {
        node.childNodes = []
        stripped = true
    }

    if ('childNodes' in node) {
        for (const childNode of node.childNodes) {
            if (stripChromeExtensionDataFromNode(childNode, needles, matchedExtensions)) {
                stripped = true
            }
        }
    }

    return stripped
}
