import { NodeTypeEnumApi } from 'products/data_modeling/frontend/generated/api.schemas'

import {
    NODE_TYPE_TAG_SETTINGS,
    STATUS_MARK_BACKGROUNDS,
    STATUS_TAG_SETTINGS,
    statusBackgroundClass,
} from './nodeStyles'

describe('nodeStyles', () => {
    it('gives every node type the API can return a label and a color', () => {
        expect(Object.keys(NODE_TYPE_TAG_SETTINGS).sort()).toEqual(Object.values(NodeTypeEnumApi).sort())
    })

    describe('statusBackgroundClass', () => {
        it.each([
            ['Completed', 'bg-success'],
            ['Failed', 'bg-danger'],
            ['Running', 'bg-warning'],
            ['Cancelled', 'bg-muted'],
            ['Skipped', 'bg-muted'],
            ['Modified', 'bg-warning'],
        ])('gives %s a %s background', (status, expected) => {
            expect(statusBackgroundClass(status)).toEqual(expected)
        })

        it('only marks a failure as a failure', () => {
            const failing = Object.keys(STATUS_TAG_SETTINGS).filter(
                (status) => statusBackgroundClass(status) === 'bg-danger'
            )
            expect(failing).toEqual(['Failed'])
        })

        it('covers every status the tags know about', () => {
            expect(Object.keys(STATUS_MARK_BACKGROUNDS).sort()).toEqual(Object.keys(STATUS_TAG_SETTINGS).sort())
        })

        it('falls back to muted for a status it does not know', () => {
            expect(statusBackgroundClass('SomethingNew')).toEqual('bg-muted')
        })
    })
})
