import { imageMetadataProhibitsAiTraining, xmpProhibitsAiTraining } from './xmp.ts'

const packet = (description: string): Buffer =>
    Buffer.from(`
        <x:xmpmeta xmlns:x="adobe:ns:meta/">
            <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
                <rdf:Description xmlns:rights="http://ns.useplus.org/ldf/xmp/1.0/" ${description} />
            </rdf:RDF>
        </x:xmpmeta>
    `)

describe('PLUS Data Mining metadata', () => {
    it.each([
        'DMI-PROHIBITED',
        'DMI-PROHIBITED-AIMLTRAINING',
        'DMI-PROHIBITED-EXCEPTSEARCHENGINEINDEXING',
        'DMI-PROHIBITED-GENAIMLTRAINING',
        'DMI-PROHIBITED-SEECONSTRAINT',
        'DMI-PROHIBITED-SEEEMBEDDEDRIGHTSEXPR',
        'DMI-PROHIBITED-SEELINKEDRIGHTSEXPR',
    ])('recognizes %s in an attribute with any valid namespace prefix', (value) => {
        expect(xmpProhibitsAiTraining(packet(`rights:DataMining="http://ns.useplus.org/ldf/vocab/${value}"`))).toBe(
            true
        )
    })

    it('recognizes the RDF resource form', () => {
        expect(
            xmpProhibitsAiTraining(
                Buffer.from(`
                    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                             xmlns:plus="http://ns.useplus.org/ldf/xmp/1.0/">
                        <rdf:Description>
                            <plus:DataMining rdf:resource="http://ns.useplus.org/ldf/vocab/DMI-PROHIBITED" />
                        </rdf:Description>
                    </rdf:RDF>
                `)
            )
        ).toBe(true)
    })

    it('does not reject an allowed value or the same property name in another namespace', () => {
        expect(xmpProhibitsAiTraining(packet('rights:DataMining="http://ns.useplus.org/ldf/vocab/DMI-ALLOWED"'))).toBe(
            false
        )
        expect(
            xmpProhibitsAiTraining(Buffer.from('<DataMining xmlns="https://example.com/">DMI-PROHIBITED</DataMining>'))
        ).toBe(false)
    })

    it('recognizes an XMP packet in a GIF application extension', () => {
        const xmp = packet('rights:DataMining="http://ns.useplus.org/ldf/vocab/DMI-PROHIBITED"')
        const trailer = Buffer.from([0x01, ...Array.from({ length: 255 }, (_, index) => 0xff - index), 0x00, 0x00])
        const gif = Buffer.concat([
            Buffer.from('GIF89a', 'ascii'),
            Buffer.from([0x21, 0xff, 0x0b]),
            Buffer.from('XMP DataXMP', 'ascii'),
            xmp,
            trailer,
        ])

        expect(imageMetadataProhibitsAiTraining(gif, undefined)).toBe(true)
    })
})
