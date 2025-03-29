import { eventWithTime } from '@posthog/rrweb-types'
import { fullSnapshotEvent } from '@posthog/rrweb-types'
import { EventType } from '@posthog/rrweb-types'
import { serializedNodeWithId } from '@posthog/rrweb-types'

import { RecordingSnapshot } from '~/types'

// we have seen some chrome extensions
// that break playback of session recordings
// let's try to strip them out
const CHROME_EXTENSION_DENY_LIST = ['dji-sru']

interface IsStrippable {
    textContent: string
    attributes: Record<string, string>
    childNodes: serializedNodeWithId[]
}

function safelyCheckCSSAttribute(
    node: serializedNodeWithId,
    attribute: string
): node is IsStrippable & serializedNodeWithId {
    const hasAttributes = 'attributes' in node && attribute in node.attributes && !!node.attributes[attribute]
    if (!hasAttributes) {
        return false
    }
    const attributeValue = node.attributes[attribute]
    if (typeof attributeValue !== 'string') {
        return false
    }
    return (
        attributeValue.includes('chrome-extension://') &&
        CHROME_EXTENSION_DENY_LIST.some((deny) => attributeValue.includes(deny))
    )
}

function safelyCheckClassAttribute(node: serializedNodeWithId): node is IsStrippable & serializedNodeWithId {
    const hasAttributes = 'attributes' in node && 'class' in node.attributes && !!node.attributes['class']
    if (!hasAttributes) {
        return false
    }
    const attributeValue = node.attributes['class']
    if (typeof attributeValue !== 'string') {
        return false
    }
    return attributeValue.includes('dji-sru')
}

function safelyCheckTagName(node: serializedNodeWithId): node is IsStrippable & serializedNodeWithId {
    const hasTagName = 'tagName' in node && typeof node.tagName === 'string'
    if (!hasTagName) {
        return false
    }
    return node.tagName.includes('dji-sru')
}

function safelyCheckDivNode(node: serializedNodeWithId): node is IsStrippable & serializedNodeWithId {
    const hasTagName = 'tagName' in node && typeof node.tagName === 'string'
    if (!hasTagName) {
        return false
    }
    if (node.tagName === 'DIV') {
        return safelyCheckClassAttribute(node)
    }
    return false
}

function stripChromeExtensionDataFromNode(node: serializedNodeWithId): boolean {
    let stripped = false

    if (safelyCheckCSSAttribute(node, 'textContent')) {
        node.textContent = ''
        stripped = true
    }
    if (safelyCheckCSSAttribute(node, '_cssText')) {
        node.attributes._cssText = ''
        stripped = true
    }
    if (safelyCheckClassAttribute(node)) {
        node.attributes['class'] = node.attributes['class'].replace('dji-sru', '')
        stripped = true
    }
    if (safelyCheckDivNode(node)) {
        node.childNodes = []
        stripped = true
    }
    if (safelyCheckTagName(node)) {
        node.childNodes = []
        stripped = true
    }

    if ('childNodes' in node) {
        for (const childNode of node.childNodes) {
            if (stripChromeExtensionDataFromNode(childNode)) {
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
        if (stripChromeExtensionDataFromNode(fullSnapshot.data.node)) {
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
