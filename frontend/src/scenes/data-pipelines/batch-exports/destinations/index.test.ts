import { DESTINATIONS } from './index'

describe('DESTINATIONS', () => {
    // HTTP posts capture-format payloads, so the backend does not export person_id to it.
    it.each(Object.keys(DESTINATIONS).filter((type) => type !== 'HTTP'))(
        '%s shows person_id in the event table preview',
        (type) => {
            expect(DESTINATIONS[type as keyof typeof DESTINATIONS].eventTableExtraFields?.person_id).toEqual(
                expect.objectContaining({ name: 'person_id', hogql_value: 'toString(person_id)' })
            )
        }
    )
})
