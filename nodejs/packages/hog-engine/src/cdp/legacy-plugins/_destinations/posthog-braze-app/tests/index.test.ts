import { ISODateString } from '../index'

test('ISODateString', () => {
    expect(ISODateString(new Date(1648458820359))).toEqual('2022-03-28T09:13:40.359Z')
})
