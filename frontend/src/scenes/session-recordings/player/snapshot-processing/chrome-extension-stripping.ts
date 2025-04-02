import { eventWithTime } from '@posthog/rrweb-types'
import { fullSnapshotEvent } from '@posthog/rrweb-types'
import { EventType } from '@posthog/rrweb-types'
import { serializedNodeWithId } from '@posthog/rrweb-types'

import { RecordingSnapshot } from '~/types'

// we have seen some chrome extensions
// that break playback of session recordings
// let's try to strip them out
const CHROME_EXTENSION_DENY_LIST = [
    // snap and read chrome extension
    'dji-sru',
    'mloajfnmjckfjbeeofcdaecbelnblden',
    // aitopia extension
    'aitopia',
    'becfinhbfclcgokjlobojlnldbfillpf',
    // loom extension
    'liecbddmkiiihnedobmlmillhodjkdmb',
]

interface IsStrippable {
    textContent: string
    attributes: Record<string, string>
    childNodes: serializedNodeWithId[]
}

function safelyCheckCSSAttribute(
    node: serializedNodeWithId,
    attribute: string,
    needles: string[]
): node is IsStrippable & serializedNodeWithId {
    const hasAttributes = 'attributes' in node && attribute in node.attributes && !!node.attributes[attribute]
    if (!hasAttributes) {
        return false
    }
    const attributeValue = node.attributes[attribute]
    if (typeof attributeValue !== 'string') {
        return false
    }

    return attributeValue.includes('chrome-extension://') && needles.some((needle) => attributeValue.includes(needle))
}

function safelyCheckClassAttribute(
    node: serializedNodeWithId,
    needle: string
): node is IsStrippable & serializedNodeWithId {
    const hasAttributes = 'attributes' in node && 'class' in node.attributes && !!node.attributes['class']
    if (!hasAttributes) {
        return false
    }
    const attributeValue = node.attributes['class']
    if (typeof attributeValue !== 'string') {
        return false
    }
    return attributeValue.includes(needle)
}

function safelyCheckTagName(
    node: serializedNodeWithId,
    needles: string[]
): node is IsStrippable & serializedNodeWithId {
    const hasTagName = 'tagName' in node && typeof node.tagName === 'string'
    if (!hasTagName) {
        return false
    }
    return needles.some((needle) => node.tagName.includes(needle))
}

function safelyCheckDivNode(
    node: serializedNodeWithId,
    needles: string[]
): node is IsStrippable & serializedNodeWithId {
    const hasTagName = 'tagName' in node && typeof node.tagName === 'string'
    if (!hasTagName) {
        return false
    }
    if (node.tagName === 'DIV') {
        return needles.some((needle) => safelyCheckClassAttribute(node, needle))
    }
    return false
}

function safelyCheckIDAttribute(
    node: serializedNodeWithId,
    needles: string[]
): node is IsStrippable & serializedNodeWithId {
    const hasID = 'attributes' in node && 'id' in node.attributes && !!node.attributes['id']
    if (!hasID) {
        return false
    }
    const idValue = node.attributes['id']
    if (typeof idValue !== 'string') {
        return false
    }
    return needles.some((needle) => idValue.includes(needle))
}

function stripChromeExtensionDataFromNode(node: serializedNodeWithId, needles: string[]): boolean {
    let stripped = false

    if (safelyCheckCSSAttribute(node, 'textContent', needles)) {
        node.textContent = ''
        stripped = true
    }
    if (safelyCheckCSSAttribute(node, '_cssText', needles)) {
        node.attributes._cssText = ''
        stripped = true
    }
    if (safelyCheckIDAttribute(node, needles)) {
        node.childNodes = []
        stripped = true
    }
    for (const needle of needles) {
        if (safelyCheckClassAttribute(node, needle)) {
            node.attributes['class'] = node.attributes['class'].replace(needle, '')
            stripped = true
        }
    }
    if (safelyCheckDivNode(node, needles)) {
        node.childNodes = []
        stripped = true
    }
    if (safelyCheckTagName(node, needles)) {
        node.childNodes = []
        stripped = true
    }

    if ('childNodes' in node) {
        for (const childNode of node.childNodes) {
            if (stripChromeExtensionDataFromNode(childNode, needles)) {
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

    for (const snapshot of snapshots) {
        if (snapshot.type !== EventType.FullSnapshot) {
            continue
        }
        const fullSnapshot = snapshot as RecordingSnapshot & fullSnapshotEvent & eventWithTime
        if (stripChromeExtensionDataFromNode(fullSnapshot.data.node, CHROME_EXTENSION_DENY_LIST)) {
            strippedChromeExtensionData = true
        }
    }

    if (strippedChromeExtensionData) {
        // insert a custom snapshot event to indicate that we've stripped the chrome extension data
        const customSnapshot: RecordingSnapshot = {
            type: EventType.Custom,
            data: {
                tag: 'chrome-extension-stripped',
                payload: {},
            },
            timestamp: snapshots[0].timestamp,
            windowId: snapshots[0].windowId,
        }
        snapshots.splice(0, 0, customSnapshot)
    }

    return snapshots
}
