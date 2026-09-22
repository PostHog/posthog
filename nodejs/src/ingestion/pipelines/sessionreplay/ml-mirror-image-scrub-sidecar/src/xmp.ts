import { type SaxesAttributeNS, SaxesParser, type SaxesTagNS } from 'saxes'

const PLUS_NAMESPACE = 'http://ns.useplus.org/ldf/xmp/1.0/'
const RDF_NAMESPACE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
const GIF_XMP_MARKER = Buffer.concat([Buffer.from([0x21, 0xff, 0x0b]), Buffer.from('XMP DataXMP', 'ascii')])
const GIF_XMP_TRAILER = Buffer.from([0x01, ...Array.from({ length: 255 }, (_, index) => 0xff - index), 0x00, 0x00])
const PROHIBITED_DATA_MINING_VALUES = new Set([
    'DMI-PROHIBITED',
    'DMI-PROHIBITED-AIMLTRAINING',
    'DMI-PROHIBITED-EXCEPTSEARCHENGINEINDEXING',
    'DMI-PROHIBITED-GENAIMLTRAINING',
    'DMI-PROHIBITED-SEECONSTRAINT',
    'DMI-PROHIBITED-SEEEMBEDDEDRIGHTSEXPR',
    'DMI-PROHIBITED-SEELINKEDRIGHTSEXPR',
])

function isProhibitedDataMiningValue(value: string): boolean {
    const identifier = value.trim().split('/').at(-1)
    return identifier !== undefined && PROHIBITED_DATA_MINING_VALUES.has(identifier)
}

function isDataMiningProperty(value: { uri: string; local: string }): boolean {
    return value.uri === PLUS_NAMESPACE && value.local === 'DataMining'
}

function resourceValue(tag: SaxesTagNS): string | undefined {
    return Object.values(tag.attributes).find(
        (attribute: SaxesAttributeNS) => attribute.uri === RDF_NAMESPACE && attribute.local === 'resource'
    )?.value
}

export function xmpProhibitsAiTraining(xmp: Buffer): boolean {
    const parser = new SaxesParser({ xmlns: true })
    let prohibited = false
    let dataMiningDepth = 0
    let dataMiningText = ''

    parser.on('opentag', (tag) => {
        for (const attribute of Object.values(tag.attributes)) {
            if (isDataMiningProperty(attribute) && isProhibitedDataMiningValue(attribute.value)) {
                prohibited = true
            }
        }
        if (dataMiningDepth > 0) {
            dataMiningDepth += 1
            return
        }
        if (isDataMiningProperty(tag)) {
            dataMiningDepth = 1
            dataMiningText = ''
            const resource = resourceValue(tag)
            if (resource && isProhibitedDataMiningValue(resource)) {
                prohibited = true
            }
        }
    })
    const collectText = (text: string): void => {
        if (dataMiningDepth > 0) {
            dataMiningText += text
        }
    }
    parser.on('text', collectText)
    parser.on('cdata', collectText)
    parser.on('closetag', () => {
        if (dataMiningDepth === 0) {
            return
        }
        dataMiningDepth -= 1
        if (dataMiningDepth === 0 && isProhibitedDataMiningValue(dataMiningText)) {
            prohibited = true
        }
    })
    parser.write(xmp.toString('utf8')).close()
    return prohibited
}

function gifXmpPackets(input: Buffer): Buffer[] {
    if (input.toString('ascii', 0, 6) !== 'GIF89a') {
        return []
    }
    const packets: Buffer[] = []
    let searchFrom = 0
    for (;;) {
        const markerOffset = input.indexOf(GIF_XMP_MARKER, searchFrom)
        if (markerOffset === -1) {
            return packets
        }
        const packetOffset = markerOffset + GIF_XMP_MARKER.length
        const trailerOffset = input.indexOf(GIF_XMP_TRAILER, packetOffset)
        if (trailerOffset === -1) {
            throw new Error('GIF XMP extension has no valid trailer')
        }
        packets.push(input.subarray(packetOffset, trailerOffset))
        searchFrom = trailerOffset + GIF_XMP_TRAILER.length
    }
}

export function imageMetadataProhibitsAiTraining(input: Buffer, decodedXmp: Buffer | undefined): boolean {
    if (decodedXmp && xmpProhibitsAiTraining(decodedXmp)) {
        return true
    }
    return gifXmpPackets(input).some(xmpProhibitsAiTraining)
}
