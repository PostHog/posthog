import { eventWithTime } from '@posthog/rrweb-types'
import { fullSnapshotEvent } from '@posthog/rrweb-types'
import { EventType } from '@posthog/rrweb-types'
import { serializedNodeWithId } from '@posthog/rrweb-types'

import { RecordingSnapshot } from '~/types'

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

export function stripChromeExtensionData(snapshots: RecordingSnapshot[]): RecordingSnapshot[] {
    // we're going to iterate the snapshots
    // if we see a full snapshot, we're going to walk the tree of nodes and child nodes
    // checking for "chrome-extension" in the attributes
    // if we find it, we're going to remove it and all of its children
    // we're going to do this in place and return the modified array
    let strippedChromeExtensionData = false
    const matchedExtensions = new Set<string>()

    for (const snapshot of snapshots) {
        if (snapshot.type !== EventType.FullSnapshot) {
            continue
        }
        const fullSnapshot = snapshot as RecordingSnapshot & fullSnapshotEvent & eventWithTime
        // it's slightly yucky that we rely on the identity of matchedExtensions here to gather matches
        // but way simpler than trying to narrow types and return a value
        if (
            stripChromeExtensionDataFromNode(
                fullSnapshot.data.node,
                Object.keys(CHROME_EXTENSION_DENY_LIST),
                matchedExtensions
            )
        ) {
            strippedChromeExtensionData = true
        }
    }

    if (strippedChromeExtensionData) {
        // insert a custom snapshot event to indicate that we've stripped the chrome extension data
        const customSnapshot: RecordingSnapshot = {
            type: EventType.Custom,
            data: {
                tag: 'chrome-extension-stripped',
                payload: {
                    extensions: Array.from(matchedExtensions),
                },
            },
            timestamp: snapshots[0].timestamp,
            windowId: snapshots[0].windowId,
        }
        snapshots.splice(0, 0, customSnapshot)
    }

    return snapshots
}
