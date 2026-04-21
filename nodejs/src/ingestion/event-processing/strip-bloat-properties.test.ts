import { droppedBloatPropertyCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { BLOAT_PROPERTIES, stripBloatProperties } from './strip-bloat-properties'

jest.mock('../../worker/ingestion/event-pipeline/metrics', () => ({
    droppedBloatPropertyCounter: {
        labels: jest.fn().mockReturnValue({ inc: jest.fn() }),
    },
}))

const mockLabels = jest.mocked(droppedBloatPropertyCounter.labels)

describe('stripBloatProperties', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each([...BLOAT_PROPERTIES])('deletes %s and increments the counter for that label', (bloatKey) => {
        const properties: Record<string, any> = { [bloatKey]: { heavy: 'cache-blob' }, other: 'kept' }

        stripBloatProperties(properties)

        expect(properties).not.toHaveProperty(bloatKey)
        expect(properties).toEqual({ other: 'kept' })
        expect(mockLabels).toHaveBeenCalledTimes(1)
        expect(mockLabels).toHaveBeenCalledWith(bloatKey)
    })

    it('strips every bloat property present and increments the counter once per stripped key', () => {
        const properties = Object.fromEntries([...BLOAT_PROPERTIES].map((key) => [key, 'v']))
        properties.other = 'kept'

        stripBloatProperties(properties)

        expect(properties).toEqual({ other: 'kept' })
        expect(mockLabels).toHaveBeenCalledTimes(BLOAT_PROPERTIES.size)
        for (const key of BLOAT_PROPERTIES) {
            expect(mockLabels).toHaveBeenCalledWith(key)
        }
    })

    it('does not increment the counter when no bloat properties are present', () => {
        const properties = { other: 'kept', another: 'also-kept' }

        stripBloatProperties(properties)

        expect(properties).toEqual({ other: 'kept', another: 'also-kept' })
        expect(mockLabels).not.toHaveBeenCalled()
    })

    it('only strips exact matches, not substring matches', () => {
        const properties = {
            ph_product_tours_foo: 'kept',
            my_ph_product_tours: 'kept',
            $product_tours_activated_at: 'kept',
            my_$override_feature_flag_payloads: 'kept',
        }

        stripBloatProperties(properties)

        expect(properties).toEqual({
            ph_product_tours_foo: 'kept',
            my_ph_product_tours: 'kept',
            $product_tours_activated_at: 'kept',
            my_$override_feature_flag_payloads: 'kept',
        })
        expect(mockLabels).not.toHaveBeenCalled()
    })
})
